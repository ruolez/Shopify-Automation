"""FastAPI routers for the Shopify Automation API"""

from .health import router as health_router
from .auth import router as auth_router
from .stores import router as stores_router
from .rules import router as rules_router
from .settings import router as settings_router
from .order_logs import router as order_logs_router
from .sync import router as sync_router
from .locations import router as locations_router
from .fraud import router as fraud_router
from .admin import router as admin_router
from .inventory import router as inventory_router
from .dashboard import router as dashboard_router

__all__ = [
    'health_router',
    'auth_router',
    'stores_router',
    'rules_router',
    'settings_router',
    'order_logs_router',
    'sync_router',
    'locations_router',
    'fraud_router',
    'admin_router',
    'inventory_router',
    'dashboard_router',
]
