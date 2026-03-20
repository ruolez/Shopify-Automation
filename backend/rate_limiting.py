"""
Rate limiting module for API endpoint protection.

Uses slowapi to protect against brute force and DoS attacks.
Supports Redis for distributed rate limiting when available.
"""
import os
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL")

if REDIS_URL:
    logger.info(f"Rate limiting using Redis storage: {REDIS_URL.split('@')[-1] if '@' in REDIS_URL else 'configured'}")
else:
    logger.info("Rate limiting using in-memory storage (not suitable for multi-process deployments)")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=REDIS_URL if REDIS_URL else None,
    default_limits=["100/minute"]
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Custom handler for rate limit exceeded errors."""
    logger.warning(
        f"Rate limit exceeded for {get_remote_address(request)}: "
        f"{request.method} {request.url.path}"
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please try again later.",
            "retry_after": str(exc.detail)
        }
    )


AUTH_LIMIT = "5/minute"
REGISTER_LIMIT = "3/hour"
ADMIN_LOGIN_LIMIT = "5/minute"
SYNC_LIMIT = "10/minute"
TRIGGER_LIMIT = "10/minute"
PASSWORD_CHANGE_LIMIT = "3/hour"
