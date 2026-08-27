"""
Tests for fetching every line item of an order (the sync query only returns the
first page). Pure — the GraphQL transport is patched.
"""
import asyncio
from unittest.mock import patch

from shopify_client import ShopifyClient


def page(edges, has_next, cursor=None):
    return {"data": {"order": {"id": "gid://shopify/Order/1", "lineItems": {
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}, "edges": edges}}}}


def edge(i):
    return {"node": {"id": f"gid://shopify/LineItem/{i}", "quantity": 1}}


class TestFetchAllLineItems:
    def setup_method(self):
        self.client = ShopifyClient("test-store.myshopify.com", "test_token")

    def test_follows_cursors_until_last_page(self):
        pages = [page([edge(1), edge(2)], True, "c1"), page([edge(3)], True, "c2"), page([edge(4)], False)]
        calls = []

        async def fake_request(query, variables=None, retry_count=3):
            calls.append(variables)
            return pages[len(calls) - 1]

        with patch.object(self.client, "_make_graphql_request", side_effect=fake_request):
            edges = asyncio.run(self.client.fetch_all_line_items("gid://shopify/Order/1"))
        assert [e["node"]["id"][-1] for e in edges] == ["1", "2", "3", "4"]
        assert [(c["first"], c["after"]) for c in calls] == [(250, None), (250, "c1"), (250, "c2")]

    def test_ensure_complete_replaces_truncated_page_in_place(self):
        order = {"id": "gid://shopify/Order/1", "name": "#1", "lineItems": {"pageInfo": {"hasNextPage": True}, "edges": [edge(1)]}}

        async def fake_request(query, variables=None, retry_count=3):
            return page([edge(1), edge(2), edge(3)], False)

        with patch.object(self.client, "_make_graphql_request", side_effect=fake_request):
            fetched = asyncio.run(self.client.ensure_complete_line_items(order))
        assert fetched is True
        assert (len(order["lineItems"]["edges"]), order["lineItems"]["pageInfo"]["hasNextPage"]) == (3, False)

    def test_ensure_complete_skips_orders_that_fit_in_one_page(self):
        order = {"id": "gid://shopify/Order/1", "lineItems": {"pageInfo": {"hasNextPage": False}, "edges": [edge(1)]}}
        with patch.object(self.client, "_make_graphql_request") as request:
            fetched = asyncio.run(self.client.ensure_complete_line_items(order))
        assert (fetched, request.call_count, len(order["lineItems"]["edges"])) == (False, 0, 1)
