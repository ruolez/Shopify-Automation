"""City/region/country for the IP address an order was placed from. Shopify's API
exposes the IP (Order.clientIp) but not its location, so it is looked up on ip-api.com.

ip-api's free endpoint is HTTP only, limited to 45 requests/minute and licensed for
non-commercial use; setting IP_API_KEY switches to the paid HTTPS endpoint."""
import ipaddress
import logging
import os
import time
from typing import Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

FIELDS = "status,city,regionName,country"
CACHE_SECONDS = 24 * 60 * 60

_cache: Dict[str, Tuple[float, Optional[str]]] = {}


def _lookup_url(ip: str) -> str:
    key = os.getenv("IP_API_KEY")
    if key:
        return f"https://pro.ip-api.com/json/{ip}?fields={FIELDS}&key={key}"
    return f"http://ip-api.com/json/{ip}?fields={FIELDS}"


async def lookup_ip_location(ip: Optional[str]) -> Optional[str]:
    """"City, Region, Country" for a public IP, or None when it is private, invalid
    or the lookup fails; answers are cached for a day"""
    try:
        if not ip or not ipaddress.ip_address(ip).is_global:
            return None
    except ValueError:
        return None

    cached = _cache.get(ip)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(_lookup_url(ip))
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        logger.warning(f"IP location lookup failed for {ip}: {e}")
        return None

    location = None
    if data.get("status") == "success":
        location = ", ".join(part for part in (data.get("city"), data.get("regionName"), data.get("country")) if part) or None
    _cache[ip] = (time.monotonic(), location)
    return location
