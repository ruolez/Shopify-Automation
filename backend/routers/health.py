"""Health check endpoints"""
import os
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/")
async def root():
    return {"message": "Shopify Multi-Store Order Management API", "status": "running"}


@router.get("/health")
def health_check():
    health = {"status": "healthy", "service": "api", "checks": {}}

    # Check Redis
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url, socket_connect_timeout=2)
        r.ping()
        health["checks"]["redis"] = "connected"
    except Exception as e:
        health["checks"]["redis"] = f"error: {str(e)}"
        health["status"] = "degraded"

    # Check Celery workers
    try:
        from tasks import celery
        inspector = celery.control.inspect(timeout=2)
        active = inspector.active()
        if active:
            health["checks"]["celery"] = f"{len(active)} worker(s) active"
        else:
            health["checks"]["celery"] = "no active workers"
            health["status"] = "degraded"
    except Exception as e:
        health["checks"]["celery"] = f"error: {str(e)}"
        health["status"] = "degraded"

    # Check Database
    try:
        from database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        health["checks"]["database"] = "connected"
    except Exception as e:
        health["checks"]["database"] = f"error: {str(e)}"
        health["status"] = "unhealthy"

    return health
