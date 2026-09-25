"""Tests for normalizing Shopify's order risk evaluation. Pure."""
from datetime import datetime, timezone

import pytest

from order_risk import order_risk, parse_risk_levels, risk_level, risk_level_rows

IP = "72.24.210.88"


def assessment(level, facts=(), provider=None):
    return {
        "riskLevel": level,
        "provider": {"id": "gid://shopify/App/1", "title": provider} if provider else None,
        "facts": [{"description": d, "sentiment": s} for d, s in facts],
    }


def risky_order(assessments, recommendation="ACCEPT", ip=IP):
    return {"id": "gid://shopify/Order/1", "clientIp": ip,
            "risk": {"recommendation": recommendation, "assessments": assessments}}


class TestRiskLevel:
    @pytest.mark.parametrize("levels, expected", [
        (["LOW"], "LOW"),
        (["LOW", "HIGH"], "HIGH"),
        (["MEDIUM", "LOW"], "MEDIUM"),
        (["NONE", "PENDING"], "PENDING"),
        (["NONE"], "NONE"),
        ([], None),
    ])
    def test_highest_level_across_assessments(self, levels, expected):
        risk = {"assessments": [{"riskLevel": level} for level in levels]}
        assert risk_level(risk) == expected

    def test_missing_risk_has_no_level(self):
        assert risk_level(None) is None

    def test_unknown_level_is_ignored(self):
        assert risk_level({"assessments": [{"riskLevel": "SOMETHING_NEW"}, {"riskLevel": "LOW"}]}) == "LOW"


class TestOrderRisk:
    def test_shopify_assessment_with_facts_and_ip(self):
        facts = [
            ("Characteristics of this order are similar to fraudulent orders observed in the past", "NEGATIVE"),
            ("Card Verification Value (CVV) is correct", "POSITIVE"),
            ("Shipping address is 71 miles from location of IP address", "NEUTRAL"),
        ]
        result = order_risk(risky_order([assessment("HIGH", facts)], recommendation="CANCEL"))
        assert result == {
            "level": "HIGH",
            "recommendation": "CANCEL",
            "assessments": [{
                "provider": None,
                "level": "HIGH",
                "facts": [{"description": d, "sentiment": s} for d, s in facts],
            }],
            "ip": IP,
            "ip_location": None,
        }

    def test_third_party_provider_is_named(self):
        result = order_risk(risky_order([assessment("LOW"), assessment("MEDIUM", provider="Signifyd")]))
        assert ([a["provider"] for a in result["assessments"]], result["level"]) == ([None, "Signifyd"], "MEDIUM")

    def test_pending_assessment(self):
        result = order_risk(risky_order([assessment("PENDING")], recommendation="NONE"))
        assert (result["level"], result["recommendation"]) == ("PENDING", "NONE")

    def test_ip_only_without_risk(self):
        assert order_risk({"clientIp": IP, "risk": None}) == {
            "level": None, "recommendation": None, "assessments": [], "ip": IP, "ip_location": None,
        }

    def test_empty_assessments_keep_recommendation(self):
        result = order_risk(risky_order([], recommendation="ACCEPT", ip=None))
        assert (result["level"], result["recommendation"], result["assessments"]) == (None, "ACCEPT", [])

    @pytest.mark.parametrize("order", [
        {},
        {"risk": None, "clientIp": None},
        {"risk": {"assessments": [], "recommendation": None}, "clientIp": ""},
    ])
    def test_nothing_to_show_is_none(self, order):
        assert order_risk(order) is None

    def test_malformed_facts_are_skipped(self):
        broken = {"riskLevel": "LOW", "provider": None, "facts": [None, {"sentiment": "POSITIVE"}, {"description": "ok", "sentiment": "POSITIVE"}]}
        result = order_risk(risky_order([broken]))
        assert result["assessments"][0]["facts"] == [{"description": "ok", "sentiment": "POSITIVE"}]


class TestParseRiskLevels:
    @pytest.mark.parametrize("value, expected", [
        (None, []),
        ("", []),
        ("HIGH", ["HIGH"]),
        ("high, Medium", ["HIGH", "MEDIUM"]),
        ("LOW,LOW,PENDING", ["LOW", "PENDING"]),
        ("HIGH,bogus,,NONE", ["HIGH"]),
    ])
    def test_keeps_known_filterable_levels_once(self, value, expected):
        assert parse_risk_levels(value) == expected


class TestRiskLevelRows:
    CHECKED_AT = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    STORE_ID = 7

    def test_one_row_per_requested_order_including_ones_shopify_did_not_return(self):
        risks = {
            "gid://shopify/Order/1": {"recommendation": "CANCEL", "assessments": [{"riskLevel": "LOW"}, {"riskLevel": "HIGH"}]},
            "gid://shopify/Order/2": {},
        }
        order_ids = ["gid://shopify/Order/1", "gid://shopify/Order/2", "gid://shopify/Order/3"]
        assert risk_level_rows(self.STORE_ID, order_ids, risks, self.CHECKED_AT) == [
            {"store_id": 7, "order_id": "gid://shopify/Order/1", "level": "HIGH", "recommendation": "CANCEL", "checked_at": self.CHECKED_AT},
            {"store_id": 7, "order_id": "gid://shopify/Order/2", "level": None, "recommendation": None, "checked_at": self.CHECKED_AT},
            {"store_id": 7, "order_id": "gid://shopify/Order/3", "level": None, "recommendation": None, "checked_at": self.CHECKED_AT},
        ]

    def test_duplicate_order_ids_yield_one_row(self):
        rows = risk_level_rows(self.STORE_ID, ["gid://shopify/Order/1"] * 2, {}, self.CHECKED_AT)
        assert [row["order_id"] for row in rows] == ["gid://shopify/Order/1"]
