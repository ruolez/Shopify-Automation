"""Shopify's order risk evaluation (risk level, recommendation, facts and the
buyer's IP) normalized from a raw Shopify order for the Orders page, and the saved
per-order risk levels the Orders page filters on."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from models import OrderLog, OrderRiskLevel

LEVEL_SEVERITY = {"NONE": 0, "PENDING": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4}
FILTERABLE_LEVELS = ("HIGH", "MEDIUM", "LOW", "PENDING")
PENDING_RECHECK_AFTER = timedelta(minutes=5)


def risk_level(risk: Optional[Dict[str, Any]]) -> Optional[str]:
    """The most severe risk level across the order's assessments (Shopify's own and
    any third-party fraud apps), or None when there is no known level"""
    levels = [(a or {}).get("riskLevel") for a in ((risk or {}).get("assessments") or [])]
    known = [level for level in levels if level in LEVEL_SEVERITY]
    return max(known, key=LEVEL_SEVERITY.__getitem__) if known else None


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
    if not assessments and not recommendation and not ip:
        return None
    return {
        "level": risk_level(risk),
        "recommendation": recommendation,
        "assessments": assessments,
        "ip": ip,
        "ip_location": None,
    }


def parse_risk_levels(value: Optional[str]) -> List[str]:
    """The Orders page's comma-separated risk_levels filter, keeping known levels once"""
    levels = []
    for part in (value or "").split(","):
        level = part.strip().upper()
        if level in FILTERABLE_LEVELS and level not in levels:
            levels.append(level)
    return levels


def risk_level_rows(store_id: int, order_ids: Iterable[str], risks: Dict[str, Dict[str, Any]],
                    checked_at: datetime) -> List[Dict[str, Any]]:
    """One order_risk_levels row per requested order; orders Shopify did not return get
    no level so they are not asked for again on every refresh"""
    rows = []
    for order_id in dict.fromkeys(order_ids):
        risk = risks.get(order_id) or {}
        rows.append({
            "store_id": store_id,
            "order_id": order_id,
            "level": risk_level(risk),
            "recommendation": risk.get("recommendation"),
            "checked_at": checked_at,
        })
    return rows


def save_order_risk_levels(db: Session, store_id: int, order_ids: Iterable[str],
                           risks: Dict[str, Dict[str, Any]]) -> None:
    rows = risk_level_rows(store_id, order_ids, risks, datetime.now(timezone.utc))
    if not rows:
        return
    statement = insert(OrderRiskLevel).values(rows)
    db.execute(statement.on_conflict_do_update(
        constraint="unique_order_risk_level",
        set_={
            "level": statement.excluded.level,
            "recommendation": statement.excluded.recommendation,
            "checked_at": statement.excluded.checked_at,
        },
    ))
    db.commit()


def orders_due_for_risk_check(db: Session, store_id: int, limit: int) -> List[str]:
    """Logged orders of a store with no saved risk level yet, or still PENDING and not
    rechecked recently; newest first"""
    recheck_before = datetime.now(timezone.utc) - PENDING_RECHECK_AFTER
    rows = db.query(OrderLog.order_id).outerjoin(
        OrderRiskLevel,
        and_(OrderRiskLevel.store_id == OrderLog.store_id, OrderRiskLevel.order_id == OrderLog.order_id),
    ).filter(
        OrderLog.store_id == store_id,
        OrderLog.order_id.like("gid://shopify/Order/%"),
        or_(
            OrderRiskLevel.id.is_(None),
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
