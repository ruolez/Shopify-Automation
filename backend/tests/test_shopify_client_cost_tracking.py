from unittest.mock import AsyncMock, patch

import httpx
import pytest

from shopify_client import ShopifyClient

QUERY = "query { shop { name } }"
SUCCESS_COST = 10


def graphql_response(body: dict) -> httpx.Response:
    return httpx.Response(200, json=body, request=httpx.Request("POST", "https://test/graphql.json"))


THROTTLED = {
    "errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}],
    "extensions": {
        "cost": {
            "requestedQueryCost": 800,
            "actualQueryCost": None,
            "throttleStatus": {"maximumAvailable": 2000, "currentlyAvailable": 100, "restoreRate": 100},
        }
    },
}

SUCCESS = {
    "data": {"shop": {"name": "Test Store"}},
    "extensions": {
        "cost": {
            "requestedQueryCost": SUCCESS_COST,
            "actualQueryCost": SUCCESS_COST,
            "throttleStatus": {"maximumAvailable": 2000, "currentlyAvailable": 1990, "restoreRate": 100},
        }
    },
}


@pytest.mark.asyncio
@patch("shopify_client.asyncio.sleep", new_callable=AsyncMock)
@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
async def test_throttled_response_with_null_cost_retries_and_succeeds(mock_post, _sleep):
    mock_post.side_effect = [graphql_response(THROTTLED), graphql_response(SUCCESS)]
    client = ShopifyClient("test-store.myshopify.com", "test_token")

    result = await client._make_graphql_request(QUERY)

    assert result == SUCCESS
    assert mock_post.call_count == 2
    assert client.get_query_cost_stats()["total_query_cost"] == SUCCESS_COST


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
async def test_null_throttle_status_does_not_break_cost_tracking(mock_post):
    body = {"data": {"shop": {"name": "Test Store"}},
            "extensions": {"cost": {"requestedQueryCost": None, "actualQueryCost": None, "throttleStatus": None}}}
    mock_post.return_value = graphql_response(body)
    client = ShopifyClient("test-store.myshopify.com", "test_token")

    result = await client._make_graphql_request(QUERY)

    assert result == body
    assert client.get_query_cost_stats()["total_query_cost"] == 0
