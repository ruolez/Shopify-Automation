"""Tests for reprocessing orders with rules (the Orders page "Retry"): customer-based
rule fields on raw Shopify orders, the batch runner's progress/cancel/resume, the
rule filter over retry results, and the queue/status/cancel endpoints.
Uses an in-memory SQLite database and a fake Shopify client; no network, no Celery."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import tasks
from database import Base, get_db
from models import OrderLog, ProcessingRule, ShopifyStore, TaskStatus, User
from rule_engine import RuleEngine, customer_order_count
from routers import order_logs as order_logs_router
from auth import get_current_user


def shopify_order(order_id, name, number_of_orders):
    customer = None if number_of_orders is None else {"email": "a@example.com", "numberOfOrders": number_of_orders}
    return {"id": order_id, "name": name, "createdAt": "2026-09-01T10:00:00Z", "tags": [], "customer": customer,
            "totalPriceSet": {"shopMoney": {"amount": "50.00", "currencyCode": "USD"}},
            "lineItems": {"edges": [], "pageInfo": {"hasNextPage": False}}}


def new_customer_rule(rule_id=1, field="fraud_is_first_time_customer", operator="equals", value=True):
    return SimpleNamespace(id=rule_id, name="New Customers", priority=1, is_active=True, delay_ms=0,
                           conditions={"operator": "AND", "conditions": [{"field": field, "operator": operator, "value": value}]},
                           actions=[{"type": "add_tag", "value": "new-customer"}])


class TestCustomerOrderCount:
    @pytest.mark.parametrize("raw,expected", [("1", 1), (3, 3), ("", None), (None, None), ("x", None)])
    def test_parses_graphql_string_counts(self, raw, expected):
        assert customer_order_count({"customer": {"numberOfOrders": raw}}) == expected

    def test_guest_checkout_has_no_count(self):
        assert customer_order_count({"customer": None}) is None


class TestCustomerFieldsOnRawOrders:
    """An order rule evaluates against the Shopify order; without a fraud analysis the
    customer fields come from the order's own customer data"""

    @pytest.mark.parametrize("count,expected", [("1", True), ("0", True), ("2", False), ("7", False)])
    def test_first_time_customer_from_order_count_without_db_session(self, count, expected):
        assert RuleEngine().evaluate_rule(new_customer_rule(), shopify_order("gid://1", "#1", count)) is expected

    def test_first_time_customer_from_order_count_when_no_analysis_exists(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None
        assert RuleEngine(db).evaluate_rule(new_customer_rule(), shopify_order("gid://1", "#1", "4")) is False

    def test_guest_checkout_keeps_the_conservative_default(self):
        assert RuleEngine().evaluate_rule(new_customer_rule(), shopify_order("gid://1", "#1", None)) is True

    @pytest.mark.parametrize("count,expected", [("1", True), ("2", False)])
    def test_customer_total_orders_field(self, count, expected):
        rule = new_customer_rule(field="customer_total_orders", operator="less_than_or_equal", value=1)
        assert RuleEngine().evaluate_rule(rule, shopify_order("gid://1", "#1", count)) is expected

    def test_customer_total_orders_is_unknown_for_guests(self):
        rule = new_customer_rule(field="customer_total_orders", operator="less_than_or_equal", value=1)
        assert RuleEngine().evaluate_rule(rule, shopify_order("gid://1", "#1", None)) is False


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, email="u@example.com", hashed_password="x", full_name="U"))
    session.add(ShopifyStore(id=10, user_id=1, shop_name="East", shop_domain="east.myshopify.com", access_token="t", is_active=True))
    session.add(ShopifyStore(id=11, user_id=1, shop_name="West", shop_domain="west.myshopify.com", access_token="t", is_active=True))
    session.add(ProcessingRule(id=1, user_id=1, name="New Customers", priority=1, is_active=True,
                               conditions={"operator": "AND", "conditions": [{"field": "fraud_is_first_time_customer", "operator": "equals", "value": True}]},
                               actions=[{"type": "add_tag", "value": "new-customer"}]))
    session.commit()
    yield session
    session.close()


ORDERS = {
    "west.myshopify.com": {"gid://shopify/Order/1": shopify_order("gid://shopify/Order/1", "#1001", "1")},
    "east.myshopify.com": {"gid://shopify/Order/2": shopify_order("gid://shopify/Order/2", "#1002", "5"),
                           "gid://shopify/Order/3": shopify_order("gid://shopify/Order/3", "#1003", "1")},
}


class FakeShopifyClient:
    lookups = []

    def __init__(self, shop_domain, access_token):
        self.shop_domain = shop_domain

    async def get_order_by_id(self, order_id, include_fraud_data=False):
        FakeShopifyClient.lookups.append((self.shop_domain, order_id))
        return ORDERS.get(self.shop_domain, {}).get(order_id)


@pytest.fixture
def fake_shopify():
    FakeShopifyClient.lookups = []
    with patch.object(tasks, "ShopifyClient", FakeShopifyClient), \
         patch.object(tasks, "_apply_rule_actions", AsyncMock(return_value=True)) as apply_actions:
        yield apply_actions


def run_retry(db, order_ids, rule_id=1, **kwargs):
    return asyncio.run(tasks.retry_order_processing(order_ids, rule_id, 1, db, **kwargs))


class TestRetryOrderProcessing:
    def test_counts_matches_skips_and_missing_orders_and_reports_progress(self, db, fake_shopify):
        progress = []
        result = run_retry(db, ["gid://shopify/Order/1", "gid://shopify/Order/2", "gid://shopify/Order/404"], progress=progress.append)
        assert result == {"processed_count": 3, "failed_count": 1, "matched_count": 1, "skipped_count": 1,
                          "total_count": 3, "cancelled": False}
        assert [(p["processed"], p["matched"], p["skipped"], p["failed"]) for p in progress] == [
            (1, 1, 0, 0), (2, 1, 1, 0), (3, 1, 1, 1), (3, 1, 1, 1)]
        assert progress[0]["current_order"] == "#1001" and progress[-1]["current_order"] is None
        assert fake_shopify.await_count == 1

    def test_match_is_logged_with_the_rule_and_misses_are_logged_as_skipped(self, db, fake_shopify):
        run_retry(db, ["gid://shopify/Order/1", "gid://shopify/Order/2"])
        rows = db.query(OrderLog).order_by(OrderLog.id).all()
        assert [(r.order_number, r.store_id, r.action, r.status, r.details.get("applied_rule_id")) for r in rows] == [
            ("#1001", 11, "retry_processing", "match", 1), ("#1002", 10, "retry_processing", "skipped", None)]

    def test_asks_the_store_the_order_was_logged_under_first(self, db, fake_shopify):
        db.add(OrderLog(user_id=1, store_id=11, order_id="gid://shopify/Order/1", order_number="#1001",
                        action="no_rules_matched", status="skipped"))
        db.commit()
        run_retry(db, ["gid://shopify/Order/1"])
        assert FakeShopifyClient.lookups == [("west.myshopify.com", "gid://shopify/Order/1")]

    def test_probes_every_store_when_the_order_was_never_logged(self, db, fake_shopify):
        run_retry(db, ["gid://shopify/Order/1"])
        assert FakeShopifyClient.lookups == [("east.myshopify.com", "gid://shopify/Order/1"),
                                             ("west.myshopify.com", "gid://shopify/Order/1")]

    def test_stops_between_orders_when_asked(self, db, fake_shopify):
        result = run_retry(db, ["gid://shopify/Order/1", "gid://shopify/Order/2"],
                           should_stop=lambda: len(FakeShopifyClient.lookups) > 0)
        assert (result["processed_count"], result["cancelled"]) == (1, True)

    def test_resumes_after_already_processed_orders(self, db, fake_shopify):
        result = run_retry(db, ["gid://shopify/Order/1", "gid://shopify/Order/2"], start_index=1)
        assert (result["processed_count"], result["skipped_count"], result["matched_count"]) == (2, 1, 0)
        assert [o for _, o in FakeShopifyClient.lookups] == ["gid://shopify/Order/2"]

    def test_inactive_rule_is_rejected(self, db, fake_shopify):
        with pytest.raises(ValueError, match="Rule 99 not found or inactive"):
            run_retry(db, ["gid://shopify/Order/1"], rule_id=99)


class TestMatchedRuleFilter:
    def test_includes_sync_matches_and_retry_matches_only(self, db):
        db.add_all([
            OrderLog(user_id=1, store_id=10, order_id="a", order_number="#1", action="applied_rule_1", status="match", details={"rule_name": "New Customers"}),
            OrderLog(user_id=1, store_id=10, order_id="b", order_number="#2", action="retry_processing", status="match", details={"applied_rule_id": 1}),
            OrderLog(user_id=1, store_id=10, order_id="c", order_number="#3", action="retry_processing", status="match", details={"applied_rule_id": 2}),
            OrderLog(user_id=1, store_id=10, order_id="d", order_number="#4", action="retry_processing", status="skipped", details={"rule_id": 1}),
            OrderLog(user_id=1, store_id=10, order_id="e", order_number="#5", action="applied_rule_12", status="match"),
        ])
        db.commit()
        rows = db.query(OrderLog.order_number).filter(order_logs_router.matched_rule(1)).order_by(OrderLog.id).all()
        assert [r[0] for r in rows] == ["#1", "#2"]


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(order_logs_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    with patch.object(order_logs_router, "create_task_status", side_effect=lambda task_id, task_name, status="pending", user_id=None: (
            db.add(TaskStatus(task_id=task_id, task_name=task_name, status=status, user_id=user_id)), db.commit())), \
         patch.object(order_logs_router.retry_orders_batch, "delay") as delay:
        yield TestClient(app), delay


class TestRetryEndpoints:
    def test_queues_a_batch_and_reports_it_as_running(self, client):
        http, delay = client
        response = http.post("/order-logs/retry", json={"order_ids": ["gid://shopify/Order/1", "gid://shopify/Order/2"], "rule_id": 1})
        assert response.status_code == 200
        body = response.json()
        assert (body["total"], body["rule_name"]) == (2, "New Customers")
        delay.assert_called_once_with(1, ["gid://shopify/Order/1", "gid://shopify/Order/2"], 1, body["task_id"])

        status = http.get("/order-logs/retry/status").json()
        assert status["recent"] == []
        assert {k: status["running"][0][k] for k in ("task_id", "status", "rule_id", "rule_name", "total", "processed", "matched", "skipped", "failed", "cancelled")} == {
            "task_id": body["task_id"], "status": "running", "rule_id": 1, "rule_name": "New Customers",
            "total": 2, "processed": 0, "matched": 0, "skipped": 0, "failed": 0, "cancelled": False}

    def test_unknown_rule_is_a_400_and_nothing_is_queued(self, client):
        http, delay = client
        response = http.post("/order-logs/retry", json={"order_ids": ["gid://shopify/Order/1"], "rule_id": 99})
        assert (response.status_code, response.json()["detail"]) == (400, "Rule 99 not found or inactive")
        assert not delay.called

    def test_cancel_marks_a_running_batch_as_cancelling(self, client):
        http, _ = client
        task_id = http.post("/order-logs/retry", json={"order_ids": ["gid://shopify/Order/1"]}).json()["task_id"]
        assert http.post(f"/order-logs/retry/{task_id}/cancel").json()["status"] == "cancelling"
        assert http.get("/order-logs/retry/status").json()["running"][0]["status"] == "cancelling"

    def test_cancel_of_someone_elses_batch_is_404(self, client):
        http, _ = client
        assert http.post("/order-logs/retry/nope/cancel").status_code == 404

    def test_finished_batches_move_to_recent(self, client, db):
        http, _ = client
        task_id = http.post("/order-logs/retry", json={"order_ids": ["gid://shopify/Order/1"]}).json()["task_id"]
        task = db.query(TaskStatus).filter(TaskStatus.task_id == task_id).first()
        task.status, task.result = "success", {**task.result, "processed": 1, "matched": 1}
        db.commit()
        status = http.get("/order-logs/retry/status").json()
        assert status["running"] == [] and [(b["task_id"], b["processed"], b["matched"]) for b in status["recent"]] == [(task_id, 1, 1)]
