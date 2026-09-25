"""Shopify webhook receiver.

Authentication is the X-Shopify-Hmac-Sha256 header (HMAC-SHA256 of the raw
request body keyed with the app client secret). Each store may have its own app,
so the secrets tried are those saved on stores for the X-Shopify-Shop-Domain
shop plus the SHOPIFY_API_SECRET env fallback — requests failing verification
get 401, as Shopify's compliance checks require. The CSRF middleware exempts
/webhooks/ for the same reason.

Handled topics:
  app/uninstalled                       → deactivate the store, flag re-auth
  orders/create, orders/updated         → enqueue an incremental store sync
  customers/data_request, customers/redact, shop/redact
                                        → GDPR compliance topics; acknowledged
                                          and logged for operator follow-up
"""
import base64
import hashlib
import hmac
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import get_db
from models import ShopifyStore
from logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _candidate_secrets(stores) -> list:
    secrets = [store.client_secret for store in stores if store.client_secret]
    env_secret = os.getenv("SHOPIFY_API_SECRET")
    if env_secret:
        secrets.append(env_secret)
    return secrets


def _verify_webhook_hmac(body: bytes, provided_hmac: str, secrets: list) -> bool:
    if not secrets:
        logger.error("No app client secret for this shop — cannot verify webhook HMAC")
        return False
    matched = False
    for secret in secrets:
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        computed = base64.b64encode(digest).decode("utf-8")
        matched |= hmac.compare_digest(computed, provided_hmac or "")
    return matched


@router.post("/shopify")
async def shopify_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    shop_domain = (request.headers.get("X-Shopify-Shop-Domain") or "").lower()

    # The shop header only selects which secrets to try; the HMAC authenticates
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.shop_domain == shop_domain
    ).all() if shop_domain else []

    if not _verify_webhook_hmac(
        body, request.headers.get("X-Shopify-Hmac-Sha256", ""), _candidate_secrets(stores)
    ):
        logger.warning("Webhook rejected: HMAC verification failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="HMAC verification failed")

    topic = request.headers.get("X-Shopify-Topic", "")
    webhook_id = request.headers.get("X-Shopify-Webhook-Id", "")

    logger.info(f"Webhook received: topic={topic} shop={shop_domain} id={webhook_id}")

    if topic == "app/uninstalled":
        for store in stores:
            if store.auth_method == "oauth":
                store.is_active = False
                store.needs_reauth = True
                logger.info(f"Store {store.id} ({shop_domain}) marked uninstalled")
        db.commit()

    elif topic in ("orders/create", "orders/updated"):
        # Event-driven sync: enqueue the existing store sync task; the per-store
        # single-flight lock coalesces bursts of order webhooks.
        from tasks import process_store_orders
        for store in stores:
            if store.is_active:
                process_store_orders.delay(store.user_id, store.id)

    elif topic in ("customers/data_request", "customers/redact", "shop/redact"):
        # GDPR compliance: acknowledge within Shopify's deadline and leave an
        # audit trail for the operator, who has 30 days to act.
        logger.warning(
            f"GDPR webhook {topic} for {shop_domain} (webhook {webhook_id}) — "
            f"operator action required within 30 days"
        )

    else:
        logger.info(f"Unhandled webhook topic {topic} for {shop_domain} — acknowledged")

    return {"received": True}
