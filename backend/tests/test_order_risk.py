"""Tests for normalizing Shopify's order risk evaluation. Pure."""
from datetime import datetime, timezone

import pytest

from order_risk import (cardholder_check, cardholder_name_match, order_risk, parse_filter_values, risk_level,
                        risk_level_rows, FILTERABLE_LEVELS, CARDHOLDER_MATCHES)

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
            "cardholder": None,
        }

    def test_third_party_provider_is_named(self):
        result = order_risk(risky_order([assessment("LOW"), assessment("MEDIUM", provider="Signifyd")]))
        assert ([a["provider"] for a in result["assessments"]], result["level"]) == ([None, "Signifyd"], "MEDIUM")

    def test_pending_assessment(self):
        result = order_risk(risky_order([assessment("PENDING")], recommendation="NONE"))
        assert (result["level"], result["recommendation"]) == ("PENDING", "NONE")

    def test_ip_only_without_risk(self):
        assert order_risk({"clientIp": IP, "risk": None}) == {
            "level": None, "recommendation": None, "assessments": [], "ip": IP, "ip_location": None, "cardholder": None,
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

    def test_cardholder_check_alone_is_shown(self):
        order = paid_order(["Charles Anderson"], billing=("Kristol", "Anderson"))
        assert order_risk(order)["cardholder"] == {
            "status": "LAST_NAME_ONLY",
            "card_names": ["Charles Anderson"],
            "billing_name": "Kristol Anderson",
            "shipping_name": None,
        }

    def test_malformed_facts_are_skipped(self):
        broken = {"riskLevel": "LOW", "provider": None, "facts": [None, {"sentiment": "POSITIVE"}, {"description": "ok", "sentiment": "POSITIVE"}]}
        result = order_risk(risky_order([broken]))
        assert result["assessments"][0]["facts"] == [{"description": "ok", "sentiment": "POSITIVE"}]


class TestParseFilterValues:
    @pytest.mark.parametrize("value, expected", [
        (None, []),
        ("", []),
        ("HIGH", ["HIGH"]),
        ("high, Medium", ["HIGH", "MEDIUM"]),
        ("LOW,LOW,PENDING", ["LOW", "PENDING"]),
        ("HIGH,bogus,,NONE", ["HIGH"]),
    ])
    def test_keeps_known_filterable_levels_once(self, value, expected):
        assert parse_filter_values(value, FILTERABLE_LEVELS) == expected

    def test_cardholder_matches(self):
        assert parse_filter_values("mismatch,last_name_only,NONE", CARDHOLDER_MATCHES) == ["MISMATCH", "LAST_NAME_ONLY"]


class TestRiskLevelRows:
    CHECKED_AT = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    STORE_ID = 7

    def test_one_row_per_requested_order_including_ones_shopify_did_not_return(self):
        orders = {
            "gid://shopify/Order/1": {
                **paid_order(["CHARLES ANDERSON"], shipping=("Kristol", "Anderson")),
                "risk": {"recommendation": "CANCEL", "assessments": [{"riskLevel": "LOW"}, {"riskLevel": "HIGH"}]},
            },
            "gid://shopify/Order/2": {"risk": None},
        }
        order_ids = ["gid://shopify/Order/1", "gid://shopify/Order/2", "gid://shopify/Order/3"]
        unchecked = {"level": None, "recommendation": None, "cardholder_match": "NONE", "cardholder_name": None,
                     "checked_at": self.CHECKED_AT}
        assert risk_level_rows(self.STORE_ID, order_ids, orders, self.CHECKED_AT) == [
            {"store_id": 7, "order_id": "gid://shopify/Order/1", "level": "HIGH", "recommendation": "CANCEL",
             "cardholder_match": "LAST_NAME_ONLY", "cardholder_name": "CHARLES ANDERSON", "checked_at": self.CHECKED_AT},
            {"store_id": 7, "order_id": "gid://shopify/Order/2", **unchecked},
            {"store_id": 7, "order_id": "gid://shopify/Order/3", **unchecked},
        ]

    def test_duplicate_order_ids_yield_one_row(self):
        rows = risk_level_rows(self.STORE_ID, ["gid://shopify/Order/1"] * 2, {}, self.CHECKED_AT)
        assert [row["order_id"] for row in rows] == ["gid://shopify/Order/1"]

    def test_long_card_names_are_cut_to_the_column_size(self):
        orders = {"gid://shopify/Order/1": paid_order(["A" * 150, "B" * 150], billing=("A", "B"))}
        row = risk_level_rows(self.STORE_ID, ["gid://shopify/Order/1"], orders, self.CHECKED_AT)[0]
        assert len(row["cardholder_name"]) == 255


class TestCardholderNameMatch:
    @pytest.mark.parametrize("card_name, order_name, expected", [
        ("Charles Anderson", "Charles Anderson", "MATCH"),
        ("CHARLES ANDERSON", "charles anderson", "MATCH"),
        ("Charles J. Anderson", "Charles Anderson", "MATCH"),
        ("C Anderson", "Charles Anderson", "MATCH"),
        ("Anderson/Charles", "Charles Anderson", "MATCH"),
        ("José Núñez", "Jose Nunez", "MATCH"),
        ("Sean O'Brien", "Sean OBrien", "MATCH"),
        ("Mary Smith", "Mary Smith-Jones", "MATCH"),
        ("Robert Smith Jr.", "Robert Smith", "MATCH"),
        ("Charles Anderson", "Kristol Anderson", "LAST_NAME_ONLY"),
        ("K Anderson", "Charles Anderson", "LAST_NAME_ONLY"),
        ("Charles Anderson", "Charles Brown", "MISMATCH"),
        ("John Smith", "Kristol Anderson", "MISMATCH"),
    ])
    def test_compares_first_and_last_names(self, card_name, order_name, expected):
        assert cardholder_name_match(card_name, order_name) == expected

    @pytest.mark.parametrize("card_name, order_name", [("", "Charles Anderson"), ("Charles Anderson", None), ("...", "A B")])
    def test_blank_name_cannot_be_compared(self, card_name, order_name):
        assert cardholder_name_match(card_name, order_name) is None


def card_payment(name, kind="SALE", status="SUCCESS"):
    return {"kind": kind, "status": status,
            "paymentDetails": {"__typename": "CardPaymentDetails", "name": name}}


def paid_order(card_names, billing=None, shipping=None, transactions=None):
    address = lambda parts: {"firstName": parts[0], "lastName": parts[1]} if parts else None
    return {
        "transactions": transactions if transactions is not None else [card_payment(n) for n in card_names],
        "billingAddress": address(billing),
        "shippingAddress": address(shipping),
    }


class TestCardholderCheck:
    def test_matching_either_billing_or_shipping_name_is_a_match(self):
        order = paid_order(["Charles Anderson"], billing=("Kristol", "Anderson"), shipping=("Charles", "Anderson"))
        assert cardholder_check(order) == {
            "status": "MATCH",
            "card_names": ["Charles Anderson"],
            "billing_name": "Kristol Anderson",
            "shipping_name": "Charles Anderson",
        }

    def test_no_name_in_common_is_a_mismatch(self):
        order = paid_order(["John Smith"], billing=("Kristol", "Anderson"), shipping=("Kristol", "Anderson"))
        assert cardholder_check(order)["status"] == "MISMATCH"

    def test_worst_card_decides_when_several_cards_paid(self):
        order = paid_order(["Kristol Anderson", "John Smith"], billing=("Kristol", "Anderson"))
        assert (cardholder_check(order)["status"], cardholder_check(order)["card_names"]) == (
            "MISMATCH", ["Kristol Anderson", "John Smith"])

    def test_only_successful_charges_and_authorizations_count(self):
        transactions = [
            card_payment("John Smith", status="FAILURE"),
            card_payment("Jane Doe", kind="REFUND"),
            card_payment("Kristol Anderson", kind="AUTHORIZATION"),
            card_payment("Kristol Anderson", kind="CAPTURE"),
        ]
        order = paid_order([], billing=("Kristol", "Anderson"), transactions=transactions)
        assert (cardholder_check(order)["status"], cardholder_check(order)["card_names"]) == ("MATCH", ["Kristol Anderson"])

    @pytest.mark.parametrize("order", [
        {},
        paid_order([], billing=("Kristol", "Anderson"), transactions=[{"kind": "SALE", "status": "SUCCESS", "paymentDetails": None}]),
        paid_order([""], billing=("Kristol", "Anderson")),
        paid_order(["Kristol Anderson"]),
    ])
    def test_nothing_to_compare_is_none(self, order):
        assert cardholder_check(order) is None
