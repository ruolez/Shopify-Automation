"""Retry behaviour of ShopifyClient._make_graphql_request for transient Shopify
failures; HTTP is served by an httpx MockTransport and sleeps are recorded, not taken."""
import asyncio

import httpx
import pytest

import shopify_client
from shopify_client import ShopifyClient, ShopifyGraphQLError, ShopifyTransientError, backoff_delay

QUERY = "query { shop { name } }"
OK = {"data": {"shop": {"name": "Tobacco Stock"}}}
INTERNAL_ERROR = {"errors": [{
    "message": "Internal error. Looks like something went wrong on our end.\nRequest ID: a9ff0709-945c-4d91-9578-ff7c62c38bfa-1790348040 (include this in support requests).",
    "extensions": {"requestId": "a9ff0709-945c-4d91-9578-ff7c62c38bfa-1790348040", "code": "INTERNAL_SERVER_ERROR"},
}]}
VALIDATION_ERROR = {"errors": [{"message": "Field 'nope' doesn't exist on type 'Shop'", "extensions": {"code": "undefinedField"}}]}


@pytest.fixture
def shopify(monkeypatch):
    """Serve queued responses to the client and record requests and backoff sleeps"""
    responses, requests, sleeps = [], [], []
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        def handle(request):
            requests.append(request)
            status, body = responses.pop(0)
            return httpx.Response(status, json=body)
        kwargs["transport"] = httpx.MockTransport(handle)
        return real_client(*args, **kwargs)

    async def record_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(shopify_client.httpx, "AsyncClient", client)
    monkeypatch.setattr(shopify_client.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(shopify_client.random, "random", lambda: 1.0)
    return responses, requests, sleeps


def run(query=QUERY):
    return asyncio.run(ShopifyClient("tobacco-stock.myshopify.com", "token")._make_graphql_request(query))


class TestTransientGraphqlErrors:
    def test_internal_server_error_is_retried_until_it_succeeds(self, shopify):
        responses, requests, sleeps = shopify
        responses.extend([(200, INTERNAL_ERROR), (200, INTERNAL_ERROR), (200, OK)])
        assert (run(), len(requests), sleeps) == (OK, 3, [2.0, 4.0])

    def test_persistent_internal_server_error_raises_retryable_error_after_all_attempts(self, shopify):
        responses, requests, sleeps = shopify
        responses.extend([(200, INTERNAL_ERROR)] * 4)
        with pytest.raises(ShopifyTransientError, match="INTERNAL_SERVER_ERROR"):
            run()
        assert (len(requests), sleeps) == (4, [2.0, 4.0, 8.0])

    def test_transient_error_is_not_a_permanent_graphql_error(self):
        assert not issubclass(ShopifyTransientError, ShopifyGraphQLError)

    def test_validation_error_fails_without_retrying(self, shopify):
        responses, requests, sleeps = shopify
        responses.append((200, VALIDATION_ERROR))
        with pytest.raises(ShopifyGraphQLError):
            run()
        assert (len(requests), sleeps) == (1, [])

    def test_http_5xx_uses_the_same_backoff(self, shopify):
        responses, requests, sleeps = shopify
        responses.extend([(503, {}), (502, {}), (200, OK)])
        assert (run(), len(requests), sleeps) == (OK, 3, [2.0, 4.0])


class TestBackoffDelay:
    @pytest.mark.parametrize("attempt, full_delay", [(0, 2.0), (1, 4.0), (2, 8.0), (3, 16.0), (4, 30.0), (9, 30.0)])
    def test_doubles_from_two_seconds_up_to_the_cap(self, monkeypatch, attempt, full_delay):
        monkeypatch.setattr(shopify_client.random, "random", lambda: 1.0)
        assert backoff_delay(attempt) == full_delay

    @pytest.mark.parametrize("attempt", [0, 2, 5])
    def test_jitter_keeps_at_least_half_the_delay(self, monkeypatch, attempt):
        monkeypatch.setattr(shopify_client.random, "random", lambda: 0.0)
        assert backoff_delay(attempt) == min(30.0, 2.0 * 2 ** attempt) / 2
