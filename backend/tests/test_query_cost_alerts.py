"""
Tests for surfacing Shopify GraphQL query-cost problems: rejection of an
over-limit query and the headroom warning. Pure tests — no database.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shopify_client import (
    MAX_SINGLE_QUERY_COST,
    ShopifyClient,
    ShopifyGraphQLError,
    query_cost_headroom_warning,
    query_cost_rejection_message,
)

ORDERS_QUERY = "query getOrdersWithFraudData($first: Int) { orders(first: $first) { edges { node { id } } } }"


def graphql_response(body):
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


def run_request(client, body):
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=graphql_response(body))) as post:
        try:
            result = asyncio.run(client._make_graphql_request(ORDERS_QUERY))
        except Exception as exc:
            result = exc
    return result, post


class TestQueryCostRejection:
    def setup_method(self):
        self.client = ShopifyClient("test-store.myshopify.com", "test_token")

    def test_max_cost_exceeded_raises_actionable_error_without_retry(self):
        body = {
            "errors": [{"message": "Query cost is 1180, which exceeds the single query max cost limit (1000).",
                        "extensions": {"code": "MAX_COST_EXCEEDED", "cost": 1180, "maxCost": 1000}}],
            "extensions": {"cost": {"requestedQueryCost": 1180, "actualQueryCost": None,
                                    "throttleStatus": {"maximumAvailable": 2000.0, "currentlyAvailable": 2000, "restoreRate": 100.0}}},
        }
        result, post = run_request(self.client, body)
        assert isinstance(result, ShopifyGraphQLError)
        assert str(result) == query_cost_rejection_message(ORDERS_QUERY, 1180)
        assert post.await_count == 1

    def test_rejection_message_names_query_cost_and_fix(self):
        message = query_cost_rejection_message(ORDERS_QUERY, 1180)
        assert ("getOrdersWithFraudData" in message and "1180" in message
                and str(MAX_SINGLE_QUERY_COST) in message and "page size" in message)

    def test_rejection_message_tolerates_missing_cost(self):
        assert "unknown" in query_cost_rejection_message("{ shop { name } }", None)

    def test_max_requested_cost_is_tracked_across_requests(self):
        for requested in (612, 950, 300):
            body = {"data": {"orders": {"edges": []}},
                    "extensions": {"cost": {"requestedQueryCost": requested, "actualQueryCost": 40,
                                            "throttleStatus": {"maximumAvailable": 2000.0, "currentlyAvailable": 1900, "restoreRate": 100.0}}}}
            result, _ = run_request(self.client, body)
            assert not isinstance(result, Exception)
        stats = self.client.get_query_cost_stats()
        assert (stats["max_requested_cost"], stats["max_requested_cost_query"]) == (950, "getOrdersWithFraudData")


class TestQueryCostHeadroomWarning:
    @pytest.mark.parametrize("requested", [0, 500, 899])
    def test_no_warning_below_ninety_percent(self, requested):
        assert query_cost_headroom_warning({"max_requested_cost": requested, "max_requested_cost_query": "getOrders"}) is None

    @pytest.mark.parametrize("requested", [900, 999, 1000])
    def test_warning_at_or_above_ninety_percent(self, requested):
        message = query_cost_headroom_warning({"max_requested_cost": requested, "max_requested_cost_query": "getOrdersWithFraudData"})
        assert ("getOrdersWithFraudData" in message and str(requested) in message
                and f"{requested / MAX_SINGLE_QUERY_COST:.0%}" in message and "page size" in message)

    def test_missing_stats_give_no_warning(self):
        assert query_cost_headroom_warning({}) is None
