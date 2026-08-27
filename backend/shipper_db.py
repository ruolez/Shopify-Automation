"""Read-only access to the shipper platform's MS SQL database (dbo.parcels).

Parcel costs are summed per Shopify order name; the driver (pymssql) is imported
lazily so the app and tests import without it installed.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, NamedTuple, Optional

from logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_PORT = 1433
# Parcel statuses that never shipped: canceled, failed, draft
EXCLUDED_PARCEL_STATUSES = (4, 9, 10)
# Wider than shipping_estimate_service.SAMPLE_WINDOW_DAYS so orders archived late still join
PARCEL_LOOKBACK_DAYS = 95

PARCEL_COSTS_SQL = """
SELECT p.order_number,
       SUM(p.cost)                                              AS total_cost,
       COUNT(*)                                                 AS parcel_count,
       SUM(CASE WHEN p.cost IS NULL THEN 1 ELSE 0 END)          AS null_cost_count,
       MAX(COALESCE(p.ship_date, CAST(p.created_at AS date)))   AS last_ship_date
FROM dbo.parcels p
WHERE p.tracking_number IS NOT NULL
  AND LTRIM(RTRIM(p.tracking_number)) <> ''
  AND (p.id_status IS NULL OR p.id_status NOT IN (4, 9, 10))
  AND p.created_at >= %s
GROUP BY p.order_number
"""
TEST_SQL = "SELECT TOP 1 id FROM dbo.parcels"


class ShipperDbError(Exception):
    """Connection or query failure against the shipper database, with a readable message"""


@dataclass(frozen=True)
class ShipperDbConfig:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_settings(cls, settings: Any) -> Optional["ShipperDbConfig"]:
        host = (getattr(settings, "shipper_db_host", None) or "").strip()
        database = (getattr(settings, "shipper_db_name", None) or "").strip()
        user = (getattr(settings, "shipper_db_user", None) or "").strip()
        if not (host and database and user):
            return None
        return cls(
            host=host,
            port=int(getattr(settings, "shipper_db_port", None) or DEFAULT_PORT),
            database=database,
            user=user,
            password=getattr(settings, "shipper_db_password", None) or "",
        )


class ParcelCost(NamedTuple):
    total_cost: float
    parcel_count: int
    last_ship_date: Optional[date]


def _describe(exc: Exception) -> str:
    """Readable text from a pymssql error, whose args are (code, message-bytes) — sometimes nested in a tuple"""
    args = getattr(exc, "args", None) or ()
    while args and isinstance(args[-1], tuple):
        args = args[-1]
    if args and isinstance(args[-1], bytes):
        message = args[-1].decode("utf-8", "replace")
        return " ".join(line.strip() for line in message.splitlines() if line.strip())
    return str(exc).strip() or exc.__class__.__name__


@contextmanager
def connect(cfg: ShipperDbConfig, login_timeout: int = 10, timeout: int = 30):
    try:
        import pymssql
    except ImportError as e:
        raise ShipperDbError("pymssql driver is not installed") from e
    try:
        conn = pymssql.connect(
            server=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            database=cfg.database,
            login_timeout=login_timeout,
            timeout=timeout,
            as_dict=True,
        )
    except Exception as e:
        raise ShipperDbError(_describe(e)) from e
    try:
        yield conn
    except ShipperDbError:
        raise
    except Exception as e:
        raise ShipperDbError(_describe(e)) from e
    finally:
        conn.close()


def test_connection(cfg: ShipperDbConfig) -> Dict[str, Any]:
    with connect(cfg) as conn:
        cursor = conn.cursor()
        cursor.execute(TEST_SQL)
        cursor.fetchall()
    return {"ok": True}


def parcel_costs_from_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, ParcelCost]:
    """Aggregate rows of PARCEL_COSTS_SQL into {order name: ParcelCost}.

    Orders with any parcel lacking a cost are skipped — a partial total would bias
    the estimate low."""
    costs: Dict[str, ParcelCost] = {}
    for row in rows:
        name = (row.get("order_number") or "").strip()
        total = row.get("total_cost")
        if not name or total is None or (row.get("null_cost_count") or 0) > 0:
            continue
        last = row.get("last_ship_date")
        if isinstance(last, datetime):
            last = last.date()
        costs[name] = ParcelCost(
            total_cost=float(total),
            parcel_count=int(row.get("parcel_count") or 1),
            last_ship_date=last,
        )
    return costs


def fetch_parcel_costs(cfg: ShipperDbConfig, since_days: int = PARCEL_LOOKBACK_DAYS) -> Dict[str, ParcelCost]:
    since = datetime.utcnow() - timedelta(days=since_days)
    with connect(cfg) as conn:
        cursor = conn.cursor()
        cursor.execute(PARCEL_COSTS_SQL, (since,))
        rows = cursor.fetchall()
    costs = parcel_costs_from_rows(rows)
    logger.info(f"Shipper DB {cfg.host}/{cfg.database}: {len(costs)} shipped orders with cost in the last {since_days} days")
    return costs
