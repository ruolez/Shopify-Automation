"""Shipping cost estimates for Order Profit.

Sync side: join shipped parcels (shipper MS SQL) to the fulfilled orders this app
already stores (fraud_analyses / fraud_analyses_archive) and keep a local
shipping_cost_samples table. Estimate side: average the cost of same-store,
same-state samples with a similar weight, widening the weight tolerance until
enough samples are found.
"""
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from logging_config import get_logger
from models import Settings, ShippingCostSample
from rule_engine import RuleEngine, calculate_order_profit

logger = get_logger(__name__)

SAMPLE_WINDOW_DAYS = 30
TOLERANCE_TIERS_G = (10, 25, 50)
MIN_SAMPLES = 3
NO_ESTIMATE = {"cost": None, "samples": 0, "tolerance_g": None}

_SAMPLE_COLUMNS = ("shipping_state", "weight_grams", "shipping_cost", "parcel_count", "shipped_at")


class Candidate(NamedTuple):
    order_name: str
    shipping_state: Optional[str]
    raw: Any  # raw_shopify_data: dict (live table) or JSON text (archive)


# --- estimate side -----------------------------------------------------------

def order_shipping_state(order: Dict[str, Any]) -> Optional[str]:
    """Same derivation as fraud_analyses.shipping_state: uppercase Shopify province name"""
    province = ((order.get("shippingAddress") or {}).get("province") or "").strip().upper()
    return province or None


def pick_samples(samples: Sequence[Tuple[float, float]], weight_grams: float) -> Tuple[Optional[int], List[float]]:
    """(tolerance used, costs) — first tier with at least MIN_SAMPLES, else whatever the widest tier has"""
    costs: List[float] = []
    for tolerance in TOLERANCE_TIERS_G:
        costs = [cost for weight, cost in samples if abs(weight - weight_grams) <= tolerance]
        if len(costs) >= MIN_SAMPLES:
            return tolerance, costs
    return (TOLERANCE_TIERS_G[-1] if costs else None), costs


def estimate_from_samples(samples: Sequence[Tuple[float, float]], weight_grams: float) -> Dict[str, Any]:
    tolerance, costs = pick_samples(samples, weight_grams)
    if not costs:
        return dict(NO_ESTIMATE)
    return {"cost": round(sum(costs) / len(costs), 2), "samples": len(costs), "tolerance_g": tolerance}


def estimate_shipping_cost(db, store_id: int, shipping_state: Optional[str], weight_grams: Optional[float],
                           exclude_order_name: Optional[str] = None, today: Optional[date] = None) -> Dict[str, Any]:
    if not shipping_state or not weight_grams or weight_grams <= 0:
        return dict(NO_ESTIMATE)
    widest = TOLERANCE_TIERS_G[-1]
    since = (today or date.today()) - timedelta(days=SAMPLE_WINDOW_DAYS)
    query = db.query(ShippingCostSample.weight_grams, ShippingCostSample.shipping_cost).filter(
        ShippingCostSample.store_id == store_id,
        ShippingCostSample.shipping_state == shipping_state,
        ShippingCostSample.shipped_at >= since,
        ShippingCostSample.weight_grams >= weight_grams - widest,
        ShippingCostSample.weight_grams <= weight_grams + widest,
    )
    if exclude_order_name:
        query = query.filter(ShippingCostSample.order_name != exclude_order_name)
    rows = [(float(weight), float(cost)) for weight, cost in query.all()]
    return estimate_from_samples(rows, weight_grams)


def compute_order_weight(order: Dict[str, Any], excluded_skus: Optional[List[str]] = None) -> Optional[float]:
    """The engine's own order_weight (grams, SKU exclusions applied); None when unknown"""
    weight = RuleEngine()._get_order_field_value("order_weight", order, excluded_skus or [])
    try:
        weight = float(weight or 0)
    except (TypeError, ValueError):
        return None
    return weight if weight > 0 else None


def resolve_shipping_cost(db, store, order: Dict[str, Any], excluded_skus: Optional[List[str]] = None,
                          settings: Optional[Settings] = None) -> Dict[str, Any]:
    """Estimated shipping for an order, falling back to the user's default shipping amount"""
    state = order_shipping_state(order)
    weight = compute_order_weight(order, excluded_skus)
    estimate = estimate_shipping_cost(db, store.id, state, weight, exclude_order_name=order.get("name"))
    if estimate["cost"] is not None:
        cost, source = estimate["cost"], "estimate"
    else:
        if settings is None:
            settings = db.query(Settings).filter(Settings.user_id == store.user_id).first()
        default_amount = float(getattr(settings, "default_shipping_amount", 0) or 0)
        cost, source = (default_amount, "default") if default_amount > 0 else (None, "none")
    return {
        "shipping_cost": cost,
        "source": source,
        "samples": estimate["samples"],
        "tolerance_g": estimate["tolerance_g"],
        "shipping_state": state,
        "weight_grams": weight,
    }


def profit_with_shipping(order: Dict[str, Any], store, excluded_skus: Optional[List[str]] = None, db=None) -> Dict[str, Any]:
    """calculate_order_profit() net of the estimated shipping cost, plus the estimate details"""
    if db is None:
        from database import get_db_session
        with get_db_session() as session:
            return profit_with_shipping(order, store, excluded_skus, session)
    info = resolve_shipping_cost(db, store, order, excluded_skus)
    profit = calculate_order_profit(order, shipping_cost=info["shipping_cost"])
    profit["shipping_estimate"] = info
    return profit


# --- sync side ---------------------------------------------------------------

def _chunks(items: List[Any], size: int) -> Iterable[List[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _archive_table_exists(db) -> bool:
    return bool(db.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'fraud_analyses_archive'"
    )).first())


def load_candidates(db, store_id: int, order_names: List[str]) -> List[Candidate]:
    """Orders of this store that have a parcel: live fraud_analyses rows plus fulfilled
    archive rows from the sample window. A parcel with a tracking number is evidence
    of shipment, so live rows count even before the hourly archive moves them."""
    if not order_names:
        return []
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=SAMPLE_WINDOW_DAYS)
    has_archive = _archive_table_exists(db)
    found: Dict[str, Candidate] = {}
    for chunk in _chunks(list(order_names), 1000):
        rows = list(db.execute(text(
            "SELECT order_name, shipping_state, raw_shopify_data FROM fraud_analyses "
            "WHERE store_id = :sid AND order_name = ANY(:names)"
        ), {"sid": store_id, "names": chunk}))
        if has_archive:
            rows += list(db.execute(text(
                "SELECT order_name, shipping_state, raw_shopify_data FROM fraud_analyses_archive "
                "WHERE store_id = :sid AND archive_reason = 'order_fulfilled' "
                "AND archived_at >= :cutoff AND order_name = ANY(:names)"
            ), {"sid": store_id, "cutoff": cutoff, "names": chunk}))
        for order_name, shipping_state, raw in rows:
            found.setdefault(order_name, Candidate(order_name, shipping_state, raw))
    return list(found.values())


def compute_sample_weight(raw: Any, excluded_skus: Optional[List[str]] = None) -> Optional[float]:
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None
    return compute_order_weight(raw, excluded_skus)


def build_samples(candidates: Iterable[Candidate], parcel_costs: Dict[str, Any], excluded_skus: Optional[List[str]],
                  *, store_id: int, user_id: int) -> List[Dict[str, Any]]:
    samples = []
    for candidate in candidates:
        parcel = parcel_costs.get(candidate.order_name)
        if not parcel:
            continue
        state = (candidate.shipping_state or "").strip().upper()
        weight = compute_sample_weight(candidate.raw, excluded_skus)
        if not state or weight is None:
            continue
        samples.append({
            "user_id": user_id,
            "store_id": store_id,
            "order_name": candidate.order_name,
            "shipping_state": state,
            "weight_grams": round(weight, 2),
            "shipping_cost": round(parcel.total_cost, 2),
            "parcel_count": parcel.parcel_count,
            "shipped_at": parcel.last_ship_date or date.today(),
        })
    return samples


def upsert_samples(db, samples: List[Dict[str, Any]]) -> None:
    for chunk in _chunks(samples, 500):
        stmt = pg_insert(ShippingCostSample).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_shipping_cost_samples_store_order",
            set_={**{column: getattr(stmt.excluded, column) for column in _SAMPLE_COLUMNS}, "synced_at": func.now()},
        )
        db.execute(stmt)
    db.commit()


def prune_samples(db, user_id: int, keep_days: int = SAMPLE_WINDOW_DAYS) -> int:
    cutoff = date.today() - timedelta(days=keep_days)
    deleted = db.query(ShippingCostSample).filter(
        ShippingCostSample.user_id == user_id,
        ShippingCostSample.shipped_at < cutoff,
    ).delete(synchronize_session=False)
    db.commit()
    return deleted


def sync_user_samples(db, user, stores, parcel_costs: Dict[str, Any], excluded_skus: List[str]) -> Dict[str, Any]:
    """Refresh shipping_cost_samples for every store of a user from one parcel-cost pull"""
    order_names = list(parcel_costs.keys())
    candidates_by_store = {store.id: load_candidates(db, store.id, order_names) for store in stores}

    owner: Dict[str, int] = {}
    ambiguous = set()
    for store_id, candidates in candidates_by_store.items():
        for candidate in candidates:
            if owner.setdefault(candidate.order_name, store_id) != store_id:
                ambiguous.add(candidate.order_name)
    if ambiguous:
        logger.warning(f"User {user.id}: {len(ambiguous)} order names exist in more than one store, skipped: {sorted(ambiguous)[:10]}")

    stats: Dict[str, Any] = {"stores": {}, "ambiguous": len(ambiguous), "samples": 0}
    for store in stores:
        candidates = [c for c in candidates_by_store[store.id] if c.order_name not in ambiguous]
        samples = build_samples(candidates, parcel_costs, excluded_skus, store_id=store.id, user_id=user.id)
        upsert_samples(db, samples)
        stats["stores"][store.id] = len(samples)
        stats["samples"] += len(samples)
        logger.info(f"Store {store.shop_domain}: {len(samples)} shipping cost samples upserted")
    return stats
