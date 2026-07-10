"""Shopify OAuth 2.0 authorization-code-grant flow (standalone app, offline token).

Complements the manual admin-API-token path: stores connected here get
auth_method="oauth". Flow per https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/authorization-code-grant

Required environment:
  SHOPIFY_API_KEY      app client id
  SHOPIFY_API_SECRET   app client secret (also used for webhook HMAC)
  APP_URL              public base URL of this deployment (e.g. https://orders.example.com)

Note: OAuth apps see only the last 60 days of orders under read_orders; the
fraud module's customer-history features need the read_all_orders scope, which
requires Shopify approval. Manual admin tokens from a custom app do not have
that restriction — keep both connection methods.
"""
import hmac
import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import redis as _redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User, ShopifyStore
from auth import get_current_user
from logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/shopify/oauth", tags=["Shopify OAuth"])

SHOP_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com$")
STATE_TTL_SECONDS = 600

DEFAULT_SCOPES = ",".join([
    "read_orders",
    "write_orders",
    "read_customers",
    "read_products",
    "read_inventory",
    "write_inventory",
    "read_locations",
    "read_assigned_fulfillment_orders",
    "read_merchant_managed_fulfillment_orders",
    "write_merchant_managed_fulfillment_orders",
    "read_third_party_fulfillment_orders",
    "write_third_party_fulfillment_orders",
])

_redis_client = _redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


def _oauth_config():
    client_id = os.getenv("SHOPIFY_API_KEY")
    client_secret = os.getenv("SHOPIFY_API_SECRET")
    app_url = (os.getenv("APP_URL") or "").rstrip("/")
    if not client_id or not client_secret or not app_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shopify OAuth is not configured (SHOPIFY_API_KEY, SHOPIFY_API_SECRET, APP_URL required)"
        )
    return client_id, client_secret, app_url


def _validate_shop_domain(shop: str) -> str:
    shop = (shop or "").strip().lower()
    if not SHOP_DOMAIN_RE.match(shop):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid shop domain — expected <store>.myshopify.com"
        )
    return shop


def verify_oauth_hmac(params: dict, client_secret: str) -> bool:
    """Verify the hmac query parameter per Shopify's OAuth spec: HMAC-SHA256 of
    the remaining query string (sorted, URL-decoded) keyed with the app secret."""
    provided = params.get("hmac", "")
    message = urlencode(sorted(
        (k, v) for k, v in params.items() if k not in ("hmac", "signature")
    ))
    computed = hmac.new(
        client_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, provided)


@router.get("/install")
async def start_install(
    shop: str,
    current_user: User = Depends(get_current_user),
):
    """Return the Shopify authorize URL for the given shop. The frontend
    redirects the browser there; the callback below completes the connection."""
    client_id, _, app_url = _oauth_config()
    shop = _validate_shop_domain(shop)

    state = secrets.token_urlsafe(32)
    _redis_client.setex(
        f"shopify_oauth_state:{state}",
        STATE_TTL_SECONDS,
        json.dumps({"user_id": current_user.id, "shop": shop}),
    )

    authorize_url = f"https://{shop}/admin/oauth/authorize?" + urlencode({
        "client_id": client_id,
        "scope": os.getenv("SHOPIFY_OAUTH_SCOPES", DEFAULT_SCOPES),
        "redirect_uri": f"{app_url}/api/shopify/oauth/callback",
        "state": state,
    })
    return {"authorize_url": authorize_url}


@router.get("/callback")
async def oauth_callback(request: Request, db: Session = Depends(get_db)):
    """OAuth redirect target: verify state + HMAC, exchange the code for an
    offline access token, upsert the store, and register webhooks."""
    client_id, client_secret, app_url = _oauth_config()
    params = dict(request.query_params)

    # 1. One-time state nonce (binds the callback to the user who started it)
    state = params.get("state", "")
    state_key = f"shopify_oauth_state:{state}"
    raw_state = _redis_client.get(state_key) if state else None
    if not raw_state:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired OAuth state")
    _redis_client.delete(state_key)
    state_data = json.loads(raw_state)

    # 2. HMAC over the query string, keyed with the app secret
    if not verify_oauth_hmac(params, client_secret):
        logger.warning(f"OAuth callback HMAC verification failed for shop={params.get('shop')}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="HMAC verification failed")

    # 3. Shop must be a plausible *.myshopify.com domain and match the state
    shop = _validate_shop_domain(params.get("shop", ""))
    if shop != state_data.get("shop"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Shop does not match OAuth state")

    code = params.get("code")
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authorization code")

    # 4. Exchange the authorization code for an access token
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(
            f"https://{shop}/admin/oauth/access_token",
            json={"client_id": client_id, "client_secret": client_secret, "code": code},
        )
    if token_resp.status_code != 200:
        logger.error(f"OAuth token exchange failed for {shop}: {token_resp.status_code} {token_resp.text}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Token exchange with Shopify failed")

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Shopify returned no access token")

    # 5. Upsert the store for the initiating user
    user_id = state_data["user_id"]
    now = datetime.now(timezone.utc)
    store = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == user_id,
        ShopifyStore.shop_domain == shop,
    ).first()

    shop_name = await _fetch_shop_name(shop, access_token) or shop.split(".")[0]

    if store is None:
        store = ShopifyStore(
            user_id=user_id,
            shop_domain=shop,
            shop_name=shop_name,
            is_active=True,
        )
        db.add(store)
    store.access_token = access_token
    store.auth_method = "oauth"
    store.granted_scopes = token_data.get("scope")
    store.installed_at = now
    store.needs_reauth = False
    store.is_active = True
    # Present only when the app is configured for expiring offline tokens
    store.refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in")
    store.token_expires_at = now + timedelta(seconds=int(expires_in)) if expires_in else None
    db.commit()
    db.refresh(store)

    # 6. Register webhooks (best effort — connection works without them)
    try:
        await _register_webhooks(shop, access_token, app_url)
    except Exception as e:
        logger.warning(f"Webhook registration failed for {shop}: {e}")

    logger.info(f"Shopify OAuth install complete for {shop} (user {user_id}, scopes: {store.granted_scopes})")

    frontend_url = os.getenv("FRONTEND_URL", app_url)
    return RedirectResponse(url=f"{frontend_url}/stores?oauth=success&shop={shop}")


async def _fetch_shop_name(shop: str, access_token: str):
    try:
        from shopify_client import ShopifyClient
        shop_info = await ShopifyClient(shop, access_token).get_shop_info()
        return shop_info.get("name")
    except Exception as e:
        logger.warning(f"Could not fetch shop name for {shop}: {e}")
        return None


WEBHOOK_TOPICS = ["APP_UNINSTALLED", "ORDERS_CREATE", "ORDERS_UPDATED"]

_WEBHOOK_CREATE_MUTATION = """
mutation webhookSubscriptionCreate($topic: WebhookSubscriptionTopic!, $webhookSubscription: WebhookSubscriptionInput!) {
    webhookSubscriptionCreate(topic: $topic, webhookSubscription: $webhookSubscription) {
        webhookSubscription {
            id
            topic
        }
        userErrors {
            field
            message
        }
    }
}
"""


async def _register_webhooks(shop: str, access_token: str, app_url: str):
    """Subscribe the app to the webhook topics the sync pipeline consumes."""
    from shopify_client import ShopifyClient
    client = ShopifyClient(shop, access_token)
    callback_url = f"{app_url}/api/webhooks/shopify"

    for topic in WEBHOOK_TOPICS:
        result = await client.execute_graphql(_WEBHOOK_CREATE_MUTATION, {
            "topic": topic,
            "webhookSubscription": {"uri": callback_url, "format": "JSON"},
        })
        payload = result.get("data", {}).get("webhookSubscriptionCreate", {})
        errors = payload.get("userErrors") or []
        # "address for this topic has already been taken" = already registered; fine
        real_errors = [e for e in errors if "taken" not in (e.get("message") or "").lower()]
        if real_errors:
            logger.warning(f"webhookSubscriptionCreate({topic}) for {shop}: {real_errors}")
        else:
            logger.info(f"Webhook {topic} registered for {shop} → {callback_url}")
