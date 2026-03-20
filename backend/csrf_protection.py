import os
import logging
from urllib.parse import urlparse
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


def get_allowed_origins() -> list[str]:
    """Get allowed origins from environment variable."""
    origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost")
    return [o.strip() for o in origins_str.split(",") if o.strip()]


def normalize_origin(origin: str) -> str:
    """Normalize origin by extracting scheme and host (without path)."""
    if not origin:
        return ""
    parsed = urlparse(origin)
    if parsed.scheme and parsed.netloc:
        port_suffix = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
        return f"{parsed.scheme}://{parsed.hostname}{port_suffix}"
    return origin


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF protection middleware that validates Origin/Referer headers
    for state-changing requests (POST, PUT, DELETE, PATCH).

    This middleware:
    - Allows safe methods (GET, HEAD, OPTIONS) without checks
    - Validates Origin or Referer header against allowed origins
    - For authenticated requests (with Authorization header), allows
      requests even without Origin if they have valid JWT
    - Blocks requests from invalid origins
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    EXEMPT_PATHS = {"/health", "/metrics", "/"}

    async def dispatch(self, request: Request, call_next):
        if request.method in self.SAFE_METHODS:
            return await call_next(request)

        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        auth_header = request.headers.get("authorization")

        check_origin = origin or referer
        allowed_origins = get_allowed_origins()

        if check_origin:
            normalized_check = normalize_origin(check_origin)
            origin_valid = any(
                normalized_check == normalize_origin(allowed)
                for allowed in allowed_origins
            )
            if not origin_valid:
                logger.warning(
                    f"CSRF: Blocked request from invalid origin: {check_origin} "
                    f"(normalized: {normalized_check}). "
                    f"Allowed: {allowed_origins}"
                )
                raise HTTPException(
                    status_code=403,
                    detail="Invalid origin"
                )
        elif not auth_header:
            logger.warning(
                f"CSRF: Request without origin or auth to {request.method} {request.url.path}"
            )
            raise HTTPException(
                status_code=403,
                detail="Origin header required"
            )

        return await call_next(request)
