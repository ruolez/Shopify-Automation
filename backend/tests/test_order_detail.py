"""Tests for the order-detail builder behind the Orders page modal. Pure."""
from types import SimpleNamespace

import pytest

from datetime import datetime, timezone

from order_detail import build_order_detail, line_item_detail, profit_snapshot
from tests.test_order_profit import line_item, money, order


def priced(item, unit_price, original=None):
    item["node"]["discountedUnitPriceAfterAllDiscountsSet"] = money(unit_price)
    item["node"]["originalUnitPriceSet"] = money(original or unit_price)
    return item


class TestLineItemDetail:
    def test_revenue_cost_profit_and_margin_per_line(self):
        node = priced(line_item(2, "20.00", title="Widget"), "35.00", "40.00")["node"]
        detail = line_item_detail(node)
        assert (detail["quantity"], detail["unit_price"], detail["unit_price_original"], detail["unit_cost"]) == (2, 35.0, 40.0, 20.0)
        assert (detail["revenue"], detail["cost"], detail["profit"], detail["margin_percent"], detail["missing_cost"]) == (70.0, 40.0, 30.0, 42.86, False)

    def test_missing_cost_is_flagged_and_counted_as_zero(self):
        detail = line_item_detail(priced(line_item(1, None), "10.00")["node"])
        assert (detail["cost"], detail["profit"], detail["missing_cost"]) == (0.0, 10.0, True)

    def test_gift_card_is_not_missing_cost(self):
        detail = line_item_detail(priced(line_item(1, None, gift_card=True), "25.00")["node"])
        assert (detail["gift_card"], detail["missing_cost"]) == (True, False)

    def test_negative_margin(self):
        detail = line_item_detail(priced(line_item(1, "30.00"), "20.00")["node"])
        assert (detail["profit"], detail["margin_percent"]) == (-10.0, -50.0)

    def test_falls_back_to_original_price_when_discounted_missing(self):
        node = line_item(3, "1.00")["node"]
        node["originalUnitPriceSet"] = money("4.00")
        assert line_item_detail(node)["revenue"] == 12.0


class TestBuildOrderDetail:
    def test_shape(self):
        data = order([priced(line_item(2, "20.00", title="Widget"), "35.00")])
        data.update({
            "id": "gid://shopify/Order/1", "createdAt": "2026-08-27T10:00:00Z", "displayFinancialStatus": "PAID",
            "displayFulfillmentStatus": "UNFULFILLED", "tags": ["low-profit"], "currentTotalPriceSet": money("118.25"),
            "customer": {"firstName": "Ada", "lastName": "Lovelace", "email": "ada@example.com", "phone": None, "numberOfOrders": 3},
            "shippingAddress": {"firstName": "Ada", "lastName": "Lovelace", "address1": "1 Main St", "city": "Reno", "province": "Nevada", "zip": "89501", "country": "United States"},
            "shippingLines": {"edges": [{"node": {"title": "Standard"}}]},
            "currentTotalWeight": 155,
        })
        profit = {"revenue": 110.0, "product_cost": 40.0, "shipping_cost": 9.77, "profit": 60.23, "margin_percent": 54.75,
                  "missing_cost_count": 0, "currency": "USD", "truncated": False,
                  "shipping_estimate": {"shipping_cost": 9.77, "source": "estimate", "samples": 4, "tolerance_g": 25, "shipping_state": "NEVADA", "weight_grams": 155.0}}
        store = SimpleNamespace(id=7, shop_name="Main", shop_domain="main.myshopify.com")
        detail = build_order_detail(data, profit, store, [{"field": "order_profit", "operator": "less_than", "value": "70", "actual": 60.23}])
        assert detail["store"] == {"id": 7, "name": "Main", "domain": "main.myshopify.com"}
        assert detail["order"] == {
            "id": "gid://shopify/Order/1", "name": "#1001", "created_at": "2026-08-27T10:00:00Z", "financial_status": "PAID",
            "fulfillment_status": "UNFULFILLED", "tags": ["low-profit"], "note": None, "currency": "USD", "subtotal": 100.0,
            "shipping_collected": 10.0, "tax": 8.25, "total": 118.25, "taxes_included": False, "shipping_method": "Standard",
            "total_weight_grams": 155, "item_count": 2, "line_items_truncated": False,
        }
        assert detail["customer"]["name"] == "Ada Lovelace" and detail["customer"]["shipping_address"]["province"] == "Nevada"
        assert detail["line_items"][0]["title"] == "Widget" and detail["line_items"][0]["profit"] == 30.0
        assert detail["shipping_estimate"]["samples"] == 4 and "shipping_estimate" not in detail["profit"]
        assert detail["profit_conditions"][0]["actual"] == 60.23
        assert detail["profit_recorded_at"] is None

    def test_recorded_at_is_passed_through_for_snapshots(self):
        data = order([priced(line_item(1, "1.00"), "2.00")])
        store = SimpleNamespace(id=1, shop_name="s", shop_domain="d")
        detail = build_order_detail(data, {"currency": "USD"}, store, profit_recorded_at="2026-09-03T12:31:00+00:00")
        assert detail["profit_recorded_at"] == "2026-09-03T12:31:00+00:00"

    def test_tolerates_missing_customer_and_addresses(self):
        data = order([priced(line_item(1, "1.00"), "2.00")])
        data.update({"customer": None, "shippingAddress": None, "billingAddress": None, "shippingLines": None})
        detail = build_order_detail(data, {"currency": "USD"}, SimpleNamespace(id=1, shop_name="s", shop_domain="d"))
        assert (detail["customer"]["name"], detail["customer"]["shipping_address"], detail["order"]["shipping_method"]) == (None, None, None)


def log(details, created_at="2026-09-03T12:31:00+00:00"):
    return SimpleNamespace(details=details, created_at=datetime.fromisoformat(created_at))


class TestProfitSnapshot:
    def test_uses_newest_log_that_recorded_a_profit(self):
        newest = {"profit": {"profit": 5.87, "shipping_estimate": {"shipping_cost": 13.21}},
                  "profit_conditions": [{"field": "order_profit", "operator": "less_than", "value": 5, "actual": 5.87}]}
        older = {"profit": {"profit": 6.1}, "profit_conditions": []}
        logs = [log({"rule_name": "hold"}, "2026-09-03T13:00:00+00:00"), log(newest), log(older, "2026-09-02T09:00:00+00:00")]
        assert profit_snapshot(logs) == {
            "profit": newest["profit"],
            "profit_conditions": newest["profit_conditions"],
            "recorded_at": "2026-09-03T12:31:00+00:00",
        }

    def test_snapshot_without_conditions_yields_empty_list(self):
        assert profit_snapshot([log({"profit": {"profit": 1.0}})])["profit_conditions"] == []

    @pytest.mark.parametrize("details", [None, {}, {"profit": None}, {"profit": "n/a"}, {"profit_conditions": [{"field": "order_profit"}]}])
    def test_none_when_no_log_recorded_a_profit(self, details):
        assert profit_snapshot([log(details)]) is None
