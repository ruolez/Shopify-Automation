"""Place a Shopify order on hold by holding every eligible fulfillment order.

Shared by fraud rules and order-processing rules so both lock down all locations
of an order the same way and report third-party/scope gaps instead of failing silently.
"""
from typing import Any, Dict, List

from logging_config import get_logger

logger = get_logger(__name__)

# Shopify FulfillmentHoldReason values a rule may choose from
HOLD_REASONS = [
    {"value": "OTHER", "label": "Other"},
    {"value": "HIGH_RISK_OF_FRAUD", "label": "High risk of fraud"},
    {"value": "INCORRECT_ADDRESS", "label": "Incorrect address"},
    {"value": "AWAITING_PAYMENT", "label": "Awaiting payment"},
    {"value": "INVENTORY_OUT_OF_STOCK", "label": "Inventory out of stock"},
    {"value": "UNKNOWN_DELIVERY_DATE", "label": "Unknown delivery date"},
    {"value": "AWAITING_RETURN_ITEMS", "label": "Awaiting return items"},
]
VALID_HOLD_REASONS = {reason["value"] for reason in HOLD_REASONS}
DEFAULT_HOLD_REASON = "OTHER"

# Fulfillment-order statuses that cannot or should not be (re-)held
INELIGIBLE_STATUSES = {"ON_HOLD", "CANCELLED", "CLOSED", "INCOMPLETE"}

UNSUPPORTED_HOLD_REASON = (
    "HOLD not in supportedActions — likely a third-party fulfillment service. "
    "Add the `write_third_party_fulfillment_orders` scope to the Shopify app and "
    "re-issue the access token to hold this FO."
)


def normalize_hold_reason(reason: Any) -> str:
    reason = (str(reason or "")).strip().upper()
    return reason if reason in VALID_HOLD_REASONS else DEFAULT_HOLD_REASON


async def hold_all_fulfillment_orders(
    client: Any,
    order_id: str,
    order_name: str,
    reason: str,
    reason_notes: str,
    trigger: str,
) -> Dict[str, Any]:
    """Hold every eligible fulfillment order of an order.

    Returns success, the held/skipped/failed fulfillment orders and a message.
    Success means everything that could be held was held and nothing was left
    unheld because of a scope/supportedActions gap."""
    reason = normalize_hold_reason(reason)
    fulfillment_orders = await client.get_fulfillment_orders_for_order(order_id)

    if not fulfillment_orders:
        logger.warning(f"No fulfillment orders found for order {order_name}. Order may be too new or already fulfilled.")
        return {
            "success": False,
            "hold_reason": reason,
            "fulfillment_orders_held": [],
            "fulfillment_orders_skipped": [],
            "fulfillment_orders_failed": [],
            "message": "No fulfillment orders available for hold",
            "fulfillment_order_id": None,
            "error": "No fulfillment orders available for hold",
        }

    held: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for fulfillment_order in fulfillment_orders:
        fo_id = fulfillment_order.get("id")
        fo_status = (fulfillment_order.get("status") or "").upper()
        location_name = (
            ((fulfillment_order.get("assignedLocation") or {}).get("location") or {}).get("name")
        ) or "unknown location"
        supported_actions = {
            (action or {}).get("action") for action in (fulfillment_order.get("supportedActions") or [])
        }

        if fo_status in INELIGIBLE_STATUSES:
            logger.info(f"Skipping fulfillment order {fo_id} at '{location_name}' for order {order_name} — status={fo_status}")
            skipped.append({"id": fo_id, "status": fo_status, "location": location_name})
            continue

        if supported_actions and "HOLD" not in supported_actions:
            logger.warning(
                f"Skipping fulfillment order {fo_id} at '{location_name}' for order {order_name} — "
                f"{UNSUPPORTED_HOLD_REASON} (supportedActions={sorted(a for a in supported_actions if a)})"
            )
            skipped.append({
                "id": fo_id,
                "status": fo_status,
                "location": location_name,
                "reason": UNSUPPORTED_HOLD_REASON,
                "supported_actions": sorted(a for a in supported_actions if a),
            })
            continue

        result = await client.apply_fulfillment_hold(
            fulfillment_order_id=fo_id,
            reason=reason,
            reason_notes=reason_notes,
            notify_merchant=True,
        )
        if result.get("success"):
            logger.info(f"Placed hold on fulfillment order {fo_id} at '{location_name}' for order {order_name} ({trigger})")
            held.append({"id": fo_id, "location": location_name})
        else:
            error_msg = (result.get("errors") or [{"message": "Unknown error"}])[0].get("message", "Unknown error")
            logger.error(f"Failed to place hold on fulfillment order {fo_id} at '{location_name}' for order {order_name}: {error_msg}")
            failed.append({"id": fo_id, "location": location_name, "error": error_msg})

    total_fos = len(fulfillment_orders)
    unheld_skipped = [s for s in skipped if s.get("reason")]
    benign_skipped = [s for s in skipped if not s.get("reason")]
    success = len(failed) == 0 and len(unheld_skipped) == 0 and (len(held) > 0 or len(benign_skipped) == total_fos)

    if failed or unheld_skipped:
        message = (
            f"Partial hold on order {order_name}: {len(held)}/{total_fos} fulfillment order(s) held, "
            f"{len(failed)} failed, {len(unheld_skipped)} could not be held (third-party or scope), "
            f"{len(benign_skipped)} already-ineligible."
        )
        logger.error(
            f"Partial hold on order {order_name}: held={[h['id'] for h in held]} failed={failed} "
            f"unheld_skipped={unheld_skipped} benign_skipped={benign_skipped}"
        )
    elif held:
        message = (
            f"Placed hold on {len(held)}/{total_fos} fulfillment orders across "
            f"{len({h['location'] for h in held})} location(s) for order {order_name} due to {trigger}."
        )
    else:
        message = (
            f"No hold applied to order {order_name}: all {total_fos} fulfillment order(s) "
            f"were already in an ineligible state ({benign_skipped})."
        )

    return {
        "success": success,
        "hold_reason": reason,
        "fulfillment_orders_held": held,
        "fulfillment_orders_skipped": skipped,
        "fulfillment_orders_failed": failed,
        "message": message,
        # Backwards-compatibility: older consumers read a single fulfillment_order_id.
        "fulfillment_order_id": held[0]["id"] if held else None,
        "error": None if success else message,
    }
