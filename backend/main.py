"""
Shopify Multi-Store Order Management API

Main application entry point - handles FastAPI app initialization,
middleware configuration, and router registration.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from logging_config import setup_logging, get_logger
from csrf_protection import CSRFMiddleware
from rate_limiting import limiter, rate_limit_exceeded_handler
from database import create_tables
from database_utils import migrate_rules_to_new_format
from tasks import test_celery_connection

from routers import (
    health_router,
    auth_router,
    stores_router,
    rules_router,
    settings_router,
    order_logs_router,
    sync_router,
    locations_router,
    fraud_router,
    admin_router,
    inventory_router,
    dashboard_router,
    shopify_oauth_router,
    webhooks_router,
)

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events."""
    logger.info("Creating database tables...")
    create_tables()
    logger.info("Database tables created successfully")

    logger.info("Checking for rule migrations...")
    migrate_rules_to_new_format()

    test_celery_connection.delay()
    yield


# Interactive API docs enumerate the full attack surface — dev/staging only
_is_production = os.getenv("ENVIRONMENT", "development") == "production"

app = FastAPI(
    title="Shopify Multi-Store Order Management",
    description="Automated order processing and tagging system for multiple Shopify stores",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

# Rate limiting configuration
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS middleware configuration
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost")
if cors_origins:
    cors_origins_list = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
else:
    cors_origins_list = ["http://localhost:3000", "http://localhost"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF protection middleware
app.add_middleware(CSRFMiddleware)

# Register all routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(stores_router)
app.include_router(rules_router)
app.include_router(settings_router)
app.include_router(order_logs_router)
app.include_router(sync_router)
app.include_router(locations_router)
app.include_router(fraud_router)
app.include_router(admin_router)
app.include_router(inventory_router)
app.include_router(dashboard_router)
app.include_router(shopify_oauth_router)
app.include_router(webhooks_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
