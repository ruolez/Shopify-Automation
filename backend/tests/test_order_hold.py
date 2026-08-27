"""
Tests for placing an order on hold (shared by fraud rules and order rules).
Pure — the Shopify client is faked.
"""
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from order_hold import (
    DEFAULT_HOLD_REASON,
    HOLD_REASONS,
    UNSUPPORTED_HOLD_REASON,
    hold_all_fulfillment_orders,
    normalize_hold_reason,
)


def fulfillment_order(fo_id, status="OPEN", location="Main", supported=("HOLD", "MOVE")):
    return {
        "id": f"gid://shopify/FulfillmentOrder/{fo_id}",
        "status": status,
        "assignedLocation": {"location": {"name": location}},
        "supportedActions": [{"action": action} for action in supported],
    }


def client_with(fulfillment_orders, hold_results=None):
    client = Mock()
    client.get_fulfillment_orders_for_order = AsyncMock(return_value=fulfillment_orders)
    client.apply_fulfillment_hold = AsyncMock(side_effect=hold_results or [{"success": True}] * len(fulfillment_orders))
    return client


def hold(client, reason="OTHER"):
    return asyncio.run(hold_all_fulfillment_orders(client, "gid://shopify/Order/1", "#1001", reason, "note", "order rule 'x'"))


class TestNormalizeHoldReason:
    @pytest.mark.parametrize("value,expected", [
        ("incorrect_address", "INCORRECT_ADDRESS"), (" HIGH_RISK_OF_FRAUD ", "HIGH_RISK_OF_FRAUD"),
        ("bogus", DEFAULT_HOLD_REASON), (None, DEFAULT_HOLD_REASON), ("", DEFAULT_HOLD_REASON),
    ])
    def test_accepts_known_reasons_and_defaults_otherwise(self, value, expected):
        assert normalize_hold_reason(value) == expected

    def test_offered_reasons_are_all_valid(self):
        assert all(normalize_hold_reason(r["value"]) == r["value"] for r in HOLD_REASONS)


class TestHoldAllFulfillmentOrders:
    def test_holds_every_open_fulfillment_order_with_the_given_reason(self):
        client = client_with([fulfillment_order(1, location="East"), fulfillment_order(2, location="West")])
        result = hold(client, reason="incorrect_address")
        assert (result["success"], [h["location"] for h in result["fulfillment_orders_held"]], result["hold_reason"]) == (
            True, ["East", "West"], "INCORRECT_ADDRESS")
        assert client.apply_fulfillment_hold.await_args_list[0].kwargs == {
            "fulfillment_order_id": "gid://shopify/FulfillmentOrder/1", "reason": "INCORRECT_ADDRESS",
            "reason_notes": "note", "notify_merchant": True,
        }

    def test_already_held_or_closed_orders_are_skipped_benignly(self):
        client = client_with([fulfillment_order(1, status="ON_HOLD"), fulfillment_order(2, status="CLOSED")])
        result = hold(client)
        assert (result["success"], result["fulfillment_orders_held"], len(result["fulfillment_orders_skipped"])) == (True, [], 2)
        assert client.apply_fulfillment_hold.await_count == 0

    def test_third_party_without_hold_support_is_reported_as_partial(self):
        client = client_with([fulfillment_order(1), fulfillment_order(2, supported=("MOVE",))])
        result = hold(client)
        assert result["success"] is False
        assert result["fulfillment_orders_skipped"][0]["reason"] == UNSUPPORTED_HOLD_REASON
        assert "1/2 fulfillment order(s) held" in result["error"]

    def test_shopify_user_error_marks_failure(self):
        client = client_with([fulfillment_order(1)], hold_results=[{"success": False, "errors": [{"message": "nope"}]}])
        result = hold(client)
        assert (result["success"], result["fulfillment_orders_failed"][0]["error"]) == (False, "nope")

    def test_no_fulfillment_orders(self):
        result = hold(client_with([]))
        assert (result["success"], result["error"]) == (False, "No fulfillment orders available for hold")


class TestRulesSchemaExposesHoldAction:
    def test_action_type_and_reasons_present(self):
        import routers.rules as rules_router
        from unittest.mock import patch
        assert any(r["value"] == "OTHER" for r in rules_router.HOLD_REASONS)
