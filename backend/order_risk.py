"""Shopify's order risk evaluation (risk level, recommendation, facts and the
buyer's IP) normalized from a raw Shopify order for the Orders page, the check of
the name on the card against the order's billing and shipping names, and the saved
per-order results the Orders page filters on."""
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from models import OrderLog, OrderRiskLevel

LEVEL_SEVERITY = {"NONE": 0, "PENDING": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4}
FILTERABLE_LEVELS = ("HIGH", "MEDIUM", "LOW", "PENDING")
PENDING_RECHECK_AFTER = timedelta(minutes=5)

# Saved cardholder_match values, worst first; NONE = no card name to compare
CARDHOLDER_MATCHES = ("MISMATCH", "LAST_NAME_ONLY", "MATCH")
NO_CARDHOLDER_MATCH = "NONE"
CARD_PAYMENT_KINDS = ("SALE", "AUTHORIZATION")
NAME_AFFIXES = {"mr", "mrs", "ms", "miss", "dr", "jr", "sr", "ii", "iii", "iv"}
CARDHOLDER_NAME_MAX_LENGTH = 255


def risk_level(risk: Optional[Dict[str, Any]]) -> Optional[str]:
    """The most severe risk level across the order's assessments (Shopify's own and
    any third-party fraud apps), or None when there is no known level"""
    levels = [(a or {}).get("riskLevel") for a in ((risk or {}).get("assessments") or [])]
    known = [level for level in levels if level in LEVEL_SEVERITY]
    return max(known, key=LEVEL_SEVERITY.__getitem__) if known else None


def _name_tokens(name: Optional[str]) -> List[str]:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"['\u2019`.]", "", text)
    return [token for token in re.split(r"[^a-z0-9]+", text) if token and token not in NAME_AFFIXES]


def _first_last_match(card: List[str], order: List[str]) -> str:
    if not set(card[1:] or card) & set(order[1:] or order):
        return "MISMATCH"
    first_card, first_order = card[0], order[0]
    initial = min(len(first_card), len(first_order)) == 1
    if first_card == first_order or (initial and first_card[0] == first_order[0]):
        return "MATCH"
    return "LAST_NAME_ONLY"


def cardholder_name_match(card_name: Optional[str], order_name: Optional[str]) -> Optional[str]:
    """MATCH when first and last names agree (a first initial, middle names, accents,
    punctuation and "LAST/FIRST" card order are tolerated), LAST_NAME_ONLY when only a
    surname is shared, MISMATCH otherwise; None when either name is blank"""
    card, order = _name_tokens(card_name), _name_tokens(order_name)
    if not card or not order:
        return None
    results = {_first_last_match(card, order), _first_last_match(card[::-1], order)}
    return next(match for match in reversed(CARDHOLDER_MATCHES) if match in results)


def _address_name(address: Optional[Dict[str, Any]]) -> Optional[str]:
    address = address or {}
    return " ".join(part for part in (address.get("firstName"), address.get("lastName")) if part) or None


def cardholder_check(order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The names on the cards that paid for the order checked against its billing and
    shipping names: each card takes its best match across those names, and the worst
    card decides. None when no card name or no order name is known."""
    card_names = list(dict.fromkeys(
        ((t.get("paymentDetails") or {}).get("name") or "").strip()
        for t in (order.get("transactions") or [])
        if isinstance(t, dict) and t.get("kind") in CARD_PAYMENT_KINDS and t.get("status") == "SUCCESS"
    ))
    card_names = [name for name in card_names if name]
    billing_name = _address_name(order.get("billingAddress"))
    shipping_name = _address_name(order.get("shippingAddress"))
    order_names = [name for name in (billing_name, shipping_name) if name]
    if not card_names or not order_names:
        return None

    def best(card_name):
        matches = {cardholder_name_match(card_name, name) for name in order_names}
        return next((m for m in reversed(CARDHOLDER_MATCHES) if m in matches), "MISMATCH")

    card_matches = {best(name) for name in card_names}
    return {
        "status": next(match for match in CARDHOLDER_MATCHES if match in card_matches),
        "card_names": card_names,
        "billing_name": billing_name,
        "shipping_name": shipping_name,
    }


def order_risk(order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What Shopify's "Order risk evaluation" panel shows; the IP location is filled
    in by the caller since Shopify's API does not provide it"""
    risk = order.get("risk") or {}
    ip = order.get("clientIp") or None
    assessments = [
        {
            "provider": ((a or {}).get("provider") or {}).get("title"),
            "level": (a or {}).get("riskLevel"),
            "facts": [
                {"description": f["description"], "sentiment": f.get("sentiment")}
                for f in ((a or {}).get("facts") or [])
                if isinstance(f, dict) and f.get("description")
            ],
        }
        for a in (risk.get("assessments") or [])
    ]
    recommendation = risk.get("recommendation")
    cardholder = cardholder_check(order)
    if not assessments and not recommendation and not ip and not cardholder:
        return None
    return {
        "level": risk_level(risk),
        "recommendation": recommendation,
        "assessments": assessments,
        "ip": ip,
        "ip_location": None,
        "cardholder": cardholder,
    }


def parse_filter_values(value: Optional[str], allowed: Iterable[str]) -> List[str]:
    """A comma-separated Orders page filter (risk_levels, cardholder_matches), keeping
    allowed values once"""
    allowed = set(allowed)
    values = []
    for part in (value or "").split(","):
        item = part.strip().upper()
        if item in allowed and item not in values:
            values.append(item)
    return values


def risk_level_rows(store_id: int, order_ids: Iterable[str], orders: Dict[str, Dict[str, Any]],
                    checked_at: datetime) -> List[Dict[str, Any]]:
    """One order_risk_levels row per requested order from its Shopify order data (risk,
    addresses, transactions); orders Shopify did not return get no level and no
    cardholder match so they are not asked for again on every refresh"""
    rows = []
    for order_id in dict.fromkeys(order_ids):
        order = orders.get(order_id) or {}
        risk = order.get("risk") or {}
        cardholder = cardholder_check(order)
        rows.append({
            "store_id": store_id,
            "order_id": order_id,
            "level": risk_level(risk),
            "recommendation": risk.get("recommendation"),
            "cardholder_match": cardholder["status"] if cardholder else NO_CARDHOLDER_MATCH,
            "cardholder_name": ", ".join(cardholder["card_names"])[:CARDHOLDER_NAME_MAX_LENGTH] if cardholder else None,
            "checked_at": checked_at,
        })
    return rows


def save_order_risk_levels(db: Session, store_id: int, order_ids: Iterable[str],
                           orders: Dict[str, Dict[str, Any]]) -> None:
    rows = risk_level_rows(store_id, order_ids, orders, datetime.now(timezone.utc))
    if not rows:
        return
    statement = insert(OrderRiskLevel).values(rows)
    db.execute(statement.on_conflict_do_update(
        constraint="unique_order_risk_level",
        set_={
            "level": statement.excluded.level,
            "recommendation": statement.excluded.recommendation,
            "cardholder_match": statement.excluded.cardholder_match,
            "cardholder_name": statement.excluded.cardholder_name,
            "checked_at": statement.excluded.checked_at,
        },
    ))
    db.commit()


def orders_due_for_risk_check(db: Session, store_id: int, limit: int) -> List[str]:
    """Logged orders of a store with no saved risk level yet (or saved before the
    cardholder name check existed), or still PENDING and not rechecked recently;
    newest first"""
    recheck_before = datetime.now(timezone.utc) - PENDING_RECHECK_AFTER
    rows = db.query(OrderLog.order_id).outerjoin(
        OrderRiskLevel,
        and_(OrderRiskLevel.store_id == OrderLog.store_id, OrderRiskLevel.order_id == OrderLog.order_id),
    ).filter(
        OrderLog.store_id == store_id,
        OrderLog.order_id.like("gid://shopify/Order/%"),
        or_(
            OrderRiskLevel.id.is_(None),
            OrderRiskLevel.cardholder_match.is_(None),
            and_(OrderRiskLevel.level == "PENDING", OrderRiskLevel.checked_at < recheck_before),
        ),
    ).group_by(OrderLog.order_id).order_by(func.max(OrderLog.created_at).desc()).limit(limit).all()
    return [row[0] for row in rows]


def has_risk_level(levels: List[str]):
    """Filter clause for OrderLog rows whose order's saved risk level is one of levels"""
    return exists().where(
        OrderRiskLevel.store_id == OrderLog.store_id,
        OrderRiskLevel.order_id == OrderLog.order_id,
        OrderRiskLevel.level.in_(levels),
    )


def has_cardholder_match(matches: List[str]):
    """Filter clause for OrderLog rows whose order's saved cardholder match is one of matches"""
    return exists().where(
        OrderRiskLevel.store_id == OrderLog.store_id,
        OrderRiskLevel.order_id == OrderLog.order_id,
        OrderRiskLevel.cardholder_match.in_(matches),
    )
