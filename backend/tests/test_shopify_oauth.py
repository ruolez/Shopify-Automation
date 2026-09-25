"""Tests for the per-store-credential Shopify OAuth flow and webhook HMAC. Pure
(fake Redis, fake DB session, fake Shopify HTTP); run with --noconftest."""
import base64
import hashlib
import hmac
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_current_user
from database import get_db
from encryption import decrypt_token
from routers import shopify_oauth, webhooks

SHOP = "tobacco-nation.myshopify.com"
CLIENT_ID = "0123456789abcdef0123456789abcdef"
CLIENT_SECRET = "shpss_per_store_secret"
ENV_SECRET = "shpss_env_secret"
ORIGIN = "http://192.168.89.23"
USER_ID = 42


class FakeRedis:
    def __init__(self):
        self.data = {}

    def setex(self, key, ttl, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)


class FakeQuery:
    def __init__(self, session):
        self.session = session

    def filter(self, *args):
        return self

    def first(self):
        return self.session.existing

    def all(self):
        return self.session.stores


class FakeSession:
    def __init__(self, existing=None, stores=()):
        self.existing = existing
        self.stores = list(stores)
        self.added = []

    def query(self, model):
        return FakeQuery(self)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def refresh(self, obj):
        pass


class FakeTokenResponse:
    status_code = 200
    text = ""

    def json(self):
        return {"access_token": "shpat_new", "scope": "read_orders"}


def fake_async_client(calls):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            calls.append((url, json))
            return FakeTokenResponse()

    return FakeAsyncClient


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(shopify_oauth, "_redis_client", fake)
    return fake


@pytest.fixture
def no_env(monkeypatch):
    for key in ("SHOPIFY_API_KEY", "SHOPIFY_API_SECRET", "APP_URL", "FRONTEND_URL"):
        monkeypatch.delenv(key, raising=False)


def make_client(session=None):
    app = FastAPI()
    app.include_router(shopify_oauth.router)
    app.include_router(webhooks.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=USER_ID)
    app.dependency_overrides[get_db] = lambda: session or FakeSession()
    return TestClient(app)


def install(client, **overrides):
    body = {"shop": SHOP, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "app_url": ORIGIN}
    body.update(overrides)
    return client.post("/shopify/oauth/install", json=body)


def signed_callback_params(state, secret, shop=SHOP):
    params = {"code": "auth-code", "shop": shop, "state": state, "timestamp": "1790000000"}
    message = urlencode(sorted(params.items()))
    params["hmac"] = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return params


class TestConfig:
    def test_reports_env_app_url(self, monkeypatch):
        monkeypatch.setenv("APP_URL", "https://orders.example.com/")
        assert make_client().get("/shopify/oauth/config").json() == {"app_url": "https://orders.example.com"}

    def test_reports_none_without_env(self, no_env):
        assert make_client().get("/shopify/oauth/config").json() == {"app_url": None}


class TestInstall:
    def test_authorize_url_uses_submitted_credentials_and_origin(self, redis, no_env):
        response = install(make_client())
        assert response.status_code == 200
        url = urlparse(response.json()["authorize_url"])
        query = parse_qs(url.query)
        assert (url.netloc, url.path) == (SHOP, "/admin/oauth/authorize")
        assert query["client_id"] == [CLIENT_ID]
        assert query["redirect_uri"] == [f"{ORIGIN}/api/shopify/oauth/callback"]

    def test_state_stores_secret_encrypted(self, redis, no_env):
        state = parse_qs(urlparse(install(make_client()).json()["authorize_url"]).query)["state"][0]
        raw = redis.get(f"shopify_oauth_state:{state}")
        stored = json.loads(raw)
        assert CLIENT_SECRET not in raw
        assert {**stored, "client_secret": decrypt_token(stored["client_secret"])} == {
            "user_id": USER_ID, "shop": SHOP, "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET, "app_url": ORIGIN,
        }

    def test_env_app_url_wins_over_origin(self, redis, no_env, monkeypatch):
        monkeypatch.setenv("APP_URL", "https://orders.example.com")
        query = parse_qs(urlparse(install(make_client()).json()["authorize_url"]).query)
        assert query["redirect_uri"] == ["https://orders.example.com/api/shopify/oauth/callback"]

    @pytest.mark.parametrize("missing", ["client_id", "client_secret"])
    def test_missing_credentials_without_env_is_400(self, redis, no_env, missing):
        response = install(make_client(), **{missing: ""})
        assert (response.status_code, response.json()["detail"]) == (
            400, "Client ID and Client Secret of the store's Shopify app are required"
        )

    def test_env_credentials_are_the_fallback(self, redis, no_env, monkeypatch):
        monkeypatch.setenv("SHOPIFY_API_KEY", "env-client-id")
        monkeypatch.setenv("SHOPIFY_API_SECRET", ENV_SECRET)
        response = install(make_client(), client_id=None, client_secret=None)
        assert parse_qs(urlparse(response.json()["authorize_url"]).query)["client_id"] == ["env-client-id"]

    @pytest.mark.parametrize("app_url", [
        "http://host/path", "javascript:alert(1)", "ftp://host", "", "http://host?x=1",
    ])
    def test_malformed_app_url_is_400(self, redis, no_env, app_url):
        assert install(make_client(), app_url=app_url).status_code == 400

    def test_invalid_shop_is_400(self, redis, no_env):
        assert install(make_client(), shop="evil.example.com").status_code == 400


class TestCallback:
    @pytest.fixture
    def started(self, redis, no_env, monkeypatch):
        calls = []
        monkeypatch.setattr(shopify_oauth.httpx, "AsyncClient", fake_async_client(calls))

        async def shop_name(shop, token):
            return "Tobacco Nation"

        webhook_calls = []

        async def register(shop, token, app_url):
            webhook_calls.append(app_url)

        monkeypatch.setattr(shopify_oauth, "_fetch_shop_name", shop_name)
        monkeypatch.setattr(shopify_oauth, "_register_webhooks", register)
        session = FakeSession()
        client = make_client(session)
        state = parse_qs(urlparse(install(client).json()["authorize_url"]).query)["state"][0]
        return SimpleNamespace(client=client, session=session, state=state, calls=calls, webhook_calls=webhook_calls)

    def test_signed_with_store_secret_saves_store_credentials(self, started):
        response = started.client.get(
            "/shopify/oauth/callback", params=signed_callback_params(started.state, CLIENT_SECRET),
            follow_redirects=False,
        )
        store = started.session.added[0]
        assert response.status_code == 307
        assert response.headers["location"] == f"{ORIGIN}/stores?oauth=success&shop={SHOP}"
        assert started.calls == [(
            f"https://{SHOP}/admin/oauth/access_token",
            {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": "auth-code"},
        )]
        assert started.webhook_calls == [ORIGIN]
        assert (store.user_id, store.auth_method, store.oauth_client_id, store.client_secret, store.access_token) == (
            USER_ID, "oauth", CLIENT_ID, CLIENT_SECRET, "shpat_new",
        )

    def test_signed_with_other_secret_is_401(self, started):
        response = started.client.get(
            "/shopify/oauth/callback", params=signed_callback_params(started.state, "shpss_wrong"),
        )
        assert (response.status_code, started.calls) == (401, [])


def webhook_hmac(body, secret):
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


class TestWebhookHmac:
    BODY = b'{"id": 1}'

    def post(self, session, secret):
        return make_client(session).post(
            "/webhooks/shopify", content=self.BODY,
            headers={
                "X-Shopify-Hmac-Sha256": webhook_hmac(self.BODY, secret),
                "X-Shopify-Shop-Domain": SHOP,
                "X-Shopify-Topic": "shop/update",
            },
        )

    def store(self, secret):
        return SimpleNamespace(client_secret=secret, is_active=True, auth_method="oauth")

    def test_accepts_store_secret(self, no_env):
        assert self.post(FakeSession(stores=[self.store(CLIENT_SECRET)]), CLIENT_SECRET).status_code == 200

    def test_accepts_env_secret_for_store_without_one(self, no_env, monkeypatch):
        monkeypatch.setenv("SHOPIFY_API_SECRET", ENV_SECRET)
        assert self.post(FakeSession(stores=[self.store(None)]), ENV_SECRET).status_code == 200

    def test_rejects_unmatched_secret(self, no_env, monkeypatch):
        monkeypatch.setenv("SHOPIFY_API_SECRET", ENV_SECRET)
        assert self.post(FakeSession(stores=[self.store(CLIENT_SECRET)]), "shpss_wrong").status_code == 401

    def test_rejects_when_no_secret_known(self, no_env):
        assert self.post(FakeSession(stores=[]), CLIENT_SECRET).status_code == 401
