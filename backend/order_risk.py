"""Shopify's order risk evaluation (risk level, recommendation, facts and the
buyer's IP) normalized from a raw Shopify order for the Orders page."""
from typing import Any, Dict, Optional

LEVEL_SEVERITY = {"NONE": 0, "PENDING": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4}


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
