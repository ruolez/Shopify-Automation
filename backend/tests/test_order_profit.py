"""
Tests for the Order Profit rule criteria (order_profit, order_profit_margin,
line_items_missing_cost). Pure engine tests — no database.
"""
import pytest
from unittest.mock import AsyncMock, Mock, patch

from rule_engine import RuleEngine, calculate_order_profit, PROFIT_FIELDS
from shopify_client import ShopifyClient


SUBTOTAL = "100.00"
SHIPPING = "10.00"
TAX = "8.25"


def money(amount, currency="USD"):
    return {"shopMoney": {"amount": amount, "currencyCode": currency}}


def line_item(quantity, unit_cost, *, current_quantity=None, variant=True,
              requires_shipping=True, gift_card=False, cost_currency="USD", title="Item"):
    node = {
        "id": f"gid://shopify/LineItem/{title}",
        "title": title,
        "quantity": quantity,
        "currentQuantity": quantity if current_quantity is None else current_quantity,
        "requiresShipping": requires_shipping,
        "product": {"id": "gid://shopify/Product/1", "isGiftCard": gift_card},
        "variant": None,
    }
    if variant:
        node["variant"] = {
            "id": "gid://shopify/ProductVariant/1",
            "sku": f"SKU-{title}",
            "inventoryItem": {
                "unitCost": None if unit_cost is None
                else {"amount": unit_cost, "currencyCode": cost_currency}
            },
        }
    return {"node": node}


def order(line_items, *, subtotal=SUBTOTAL, shipping=SHIPPING, tax=TAX,
          taxes_included=False, has_next_page=False):
    return {
        "name": "#1001",
        "taxesIncluded": taxes_included,
        "totalPriceSet": money("118.25"),
        "currentSubtotalPriceSet": money(subtotal),
        "currentShippingPriceSet": money(shipping),
        "currentTotalTaxSet": money(tax),
        "lineItems": {"pageInfo": {"hasNextPage": has_next_page}, "edges": line_items},
    }


class TestCalculateOrderProfit:
    def test_revenue_is_subtotal_plus_shipping_minus_cost(self):
        result = calculate_order_profit(order([line_item(2, "20.00"), line_item(1, "15.00")]))
        assert result == {
            "revenue": 110.0,
            "product_cost": 55.0,
            "profit": 55.0,
            "margin_percent": 50.0,
            "missing_cost_count": 0,
            "shipping_cost": None,
            "currency": "USD",
            "truncated": False,
        }

    def test_tax_is_excluded_from_revenue_for_tax_exclusive_store(self):
        result = calculate_order_profit(order([line_item(1, "10.00")], taxes_included=False))
        assert result["revenue"] == 110.0

    def test_tax_is_removed_from_subtotal_for_tax_inclusive_store(self):
        result = calculate_order_profit(order([line_item(1, "10.00")], taxes_included=True))
        assert result["revenue"] == pytest.approx(110.0 - 8.25)

    def test_negative_profit(self):
        result = calculate_order_profit(order([line_item(3, "50.00")]))
        assert (result["profit"], result["margin_percent"]) == (-40.0, pytest.approx(-36.36))

    def test_zero_revenue_gives_no_margin(self):
        result = calculate_order_profit(order([line_item(1, "5.00")], subtotal="0.00", shipping="0.00"))
        assert (result["profit"], result["margin_percent"]) == (-5.0, None)

    def test_missing_unit_cost_counts_as_zero_and_is_reported(self):
        result = calculate_order_profit(order([line_item(2, "20.00"), line_item(1, None)]))
        assert (result["product_cost"], result["missing_cost_count"]) == (40.0, 1)

    def test_deleted_product_variant_counts_as_missing(self):
        result = calculate_order_profit(order([line_item(1, None, variant=False, requires_shipping=True)]))
        assert (result["product_cost"], result["missing_cost_count"]) == (0.0, 1)

    def test_tip_without_variant_is_not_missing_cost(self):
        result = calculate_order_profit(order([line_item(1, None, variant=False, requires_shipping=False)]))
        assert (result["product_cost"], result["missing_cost_count"]) == (0.0, 0)

    def test_gift_card_is_not_missing_cost(self):
        result = calculate_order_profit(order([line_item(1, None, gift_card=True)]))
        assert (result["product_cost"], result["missing_cost_count"]) == (0.0, 0)

    def test_current_quantity_is_used_over_original_quantity(self):
        result = calculate_order_profit(order([line_item(5, "10.00", current_quantity=2)]))
        assert result["product_cost"] == 20.0

    def test_removed_line_item_without_cost_is_ignored(self):
        result = calculate_order_profit(order([line_item(1, None, current_quantity=0)]))
        assert result["missing_cost_count"] == 0

    def test_falls_back_to_quantity_when_current_quantity_absent(self):
        item = line_item(3, "10.00")
        del item["node"]["currentQuantity"]
        assert calculate_order_profit(order([item]))["product_cost"] == 30.0

    def test_truncated_line_items_make_profit_unknown(self):
        result = calculate_order_profit(order([line_item(1, "10.00")], has_next_page=True))
        assert result == {
            "revenue": None,
            "product_cost": None,
            "profit": None,
            "margin_percent": None,
            "missing_cost_count": None,
            "shipping_cost": None,
            "currency": None,
            "truncated": True,
        }

    def test_payload_without_profit_fields_is_unknown(self):
        legacy_order = {"totalPriceSet": money("150.00"), "lineItems": {"edges": [line_item(1, "10.00")]}}
        result = calculate_order_profit(legacy_order)
        assert (result["profit"], result["missing_cost_count"], result["truncated"]) == (None, None, False)

    def test_null_nested_objects_are_tolerated(self):
        data = order([{"node": {"quantity": 1, "product": None, "variant": {"inventoryItem": None}}}])
        data["currentShippingPriceSet"] = None
        result = calculate_order_profit(data)
        assert (result["revenue"], result["missing_cost_count"]) == (100.0, 1)


class TestProfitRuleFields:
    def setup_method(self):
        self.engine = RuleEngine()

    def test_schema_exposes_profit_fields_as_numbers(self):
        fields = {f["field"]: f["type"] for f in self.engine.get_available_fields()}
        assert {name: fields.get(name) for name in PROFIT_FIELDS} == {
            "order_profit": "number",
            "order_profit_margin": "number",
            "line_items_missing_cost": "number",
            "estimated_shipping_cost": "number",
            "shipping_estimate_samples": "number",
        }

    def test_field_extraction(self):
        data = order([line_item(2, "20.00"), line_item(1, None)])
        extracted = {field: self.engine._get_order_field_value(field, data) for field in PROFIT_FIELDS}
        assert extracted == {
            "order_profit": 70.0,
            "order_profit_margin": pytest.approx(63.64),
            "line_items_missing_cost": 1,
            "estimated_shipping_cost": None,
            "shipping_estimate_samples": 0,
        }

    @staticmethod
    def rule(conditions, operator="AND"):
        rule = Mock()
        rule.id = 1
        rule.name = "Profit rule"
        rule.conditions = {"operator": operator, "conditions": conditions}
        return rule

    def test_low_profit_rule_matches(self):
        rule = self.rule([{"field": "order_profit", "operator": "less_than", "value": "5"}])
        assert self.engine.evaluate_rule(rule, order([line_item(2, "55.00")])) is True
        assert self.engine.evaluate_rule(rule, order([line_item(1, "10.00")])) is False

    def test_margin_rule_matches(self):
        rule = self.rule([{"field": "order_profit_margin", "operator": "less_than", "value": "15"}])
        assert self.engine.evaluate_rule(rule, order([line_item(1, "100.00")])) is True
        assert self.engine.evaluate_rule(rule, order([line_item(1, "10.00")])) is False

    def test_missing_cost_rule_matches(self):
        rule = self.rule([{"field": "line_items_missing_cost", "operator": "greater_than", "value": "0"}])
        assert self.engine.evaluate_rule(rule, order([line_item(1, None)])) is True
        assert self.engine.evaluate_rule(rule, order([line_item(1, "1.00")])) is False

    def test_truncated_order_never_matches_profit_rule(self):
        rule = self.rule([{"field": "order_profit", "operator": "less_than", "value": "1000"}])
        assert self.engine.evaluate_rule(rule, order([line_item(1, "10.00")], has_next_page=True)) is False

    def test_profit_combines_with_existing_fields(self):
        rule = self.rule([
            {"field": "order_total", "operator": "greater_than", "value": "100"},
            {"field": "order_profit", "operator": "less_than", "value": "60"},
        ])
        assert self.engine.evaluate_rule(rule, order([line_item(1, "55.00")])) is True
        assert self.engine.evaluate_rule(rule, order([line_item(1, "10.00")])) is False


REQUIRED_QUERY_FRAGMENTS = ("unitCost", "currentSubtotalPriceSet", "currentShippingPriceSet",
                            "currentTotalTaxSet", "taxesIncluded", "isGiftCard", "currentQuantity",
                            "requiresShipping")


class TestOrderQueriesSelectProfitFields:
    """Every order query used for rule evaluation must select the profit inputs,
    including the f-string built ones where a brace mistake would break the query."""

    @staticmethod
    def captured_query(coro_factory):
        captured = {}

        async def fake_request(query, variables=None, retry_count=3):
            captured["query"] = query
            return {"data": {"orders": {"edges": [], "pageInfo": {}}, "order": None}}

        client = ShopifyClient("test-store.myshopify.com", "test_token")
        with patch.object(client, "_make_graphql_request", side_effect=fake_request):
            import asyncio
            asyncio.run(coro_factory(client))
        return captured["query"]

    @pytest.mark.parametrize("include_fraud_data", [True, False])
    def test_get_orders(self, include_fraud_data):
        query = self.captured_query(lambda c: c.get_orders(limit=5, include_fraud_data=include_fraud_data))
        assert [frag for frag in REQUIRED_QUERY_FRAGMENTS if frag not in query] == []
        assert "{{" not in query

    @pytest.mark.parametrize("include_fraud_data", [True, False])
    def test_get_order_by_id(self, include_fraud_data):
        query = self.captured_query(
            lambda c: c.get_order_by_id("gid://shopify/Order/1", include_fraud_data=include_fraud_data)
        )
        assert [frag for frag in REQUIRED_QUERY_FRAGMENTS if frag not in query] == []
        assert "{{" not in query

    @pytest.mark.parametrize("level", ["minimal", "balanced", "full"])
    def test_get_orders_optimized(self, level):
        query = self.captured_query(
            lambda c: c.get_orders_optimized(limit=5, include_fraud_data=True, optimization_level=level)
        )
        assert [frag for frag in REQUIRED_QUERY_FRAGMENTS if frag not in query] == []
        assert "{{" not in query


class TestOrderTotalNotShadowedByFraudFields:
    """order_total is also a fraud-analysis key; on a raw Shopify order it must still read totalPriceSet."""

    def test_order_total_reads_total_price_set(self):
        engine = RuleEngine()
        assert engine._get_order_field_value("order_total", {"totalPriceSet": money("150.00")}) == 150.0

    def test_fraud_dict_value_still_wins(self):
        engine = RuleEngine()
        assert engine._get_order_field_value("order_total", {"order_total": 42.5, "totalPriceSet": money("150.00")}) == 42.5


class TestNumericEqualsCoercion:
    """Rule values are strings from the UI; numeric order fields must still compare equal"""

    def setup_method(self):
        self.engine = RuleEngine()

    @pytest.mark.parametrize("actual,expected,result", [(0, "0", True), (2, "2", True), (2.0, "2", True), (3, "2", False), (2, "abc", False)])
    def test_equals_with_numeric_strings(self, actual, expected, result):
        assert self.engine._equals(actual, expected) is result

    @pytest.mark.parametrize("actual,expected,result", [(0, "0", False), (3, "2", True)])
    def test_not_equals_with_numeric_strings(self, actual, expected, result):
        assert self.engine._not_equals(actual, expected) is result

    def test_boolean_and_string_semantics_unchanged(self):
        assert (self.engine._equals(True, "true"), self.engine._equals("CA", "CA"), self.engine._equals(True, "1")) == (True, True, True)

    def test_rule_with_equals_on_count_field_matches(self):
        rule = Mock(); rule.id = 1; rule.name = "one item"
        rule.conditions = {"operator": "AND", "conditions": [{"field": "line_item_count", "operator": "equals", "value": "1"}]}
        assert self.engine.evaluate_rule(rule, order([line_item(1, "1.00")])) is True


class TestProfitConditionsInMatchDetails:
    """The order log records each profit threshold with the value the order had"""

    def setup_method(self):
        from tasks import _profit_conditions, _rule_match_details
        self.profit_conditions = _profit_conditions
        self.match_details = _rule_match_details

    @staticmethod
    def rule(conditions):
        rule = Mock(); rule.id = 1; rule.name = "Low profit"
        rule.conditions = conditions
        return rule

    def test_maps_each_profit_field_to_its_actual_value(self):
        profit = {"profit": 12.5, "margin_percent": 20.0, "missing_cost_count": 1,
                  "shipping_estimate": {"shipping_cost": 6.0, "samples": 4}}
        rule = self.rule({"operator": "AND", "conditions": [
            {"field": "order_profit", "operator": "less_than", "value": "15"},
            {"field": "order_profit_margin", "operator": "less_than", "value": "25"},
            {"field": "shipping_estimate_samples", "operator": "greater_than", "value": "0"},
            {"field": "shipping_country", "operator": "equals", "value": "US"},
        ]})
        assert self.profit_conditions(rule, profit) == [
            {"field": "order_profit", "operator": "less_than", "value": "15", "actual": 12.5},
            {"field": "order_profit_margin", "operator": "less_than", "value": "25", "actual": 20.0},
            {"field": "shipping_estimate_samples", "operator": "greater_than", "value": "0", "actual": 4},
        ]

    def test_legacy_list_conditions_are_supported(self):
        rule = self.rule([{"field": "order_profit", "operator": "less_than", "value": "5"}])
        assert self.profit_conditions(rule, {"profit": -1.0}) == [
            {"field": "order_profit", "operator": "less_than", "value": "5", "actual": -1.0}]

    def test_match_details_include_profit_and_thresholds_without_store(self):
        rule = self.rule({"operator": "AND", "conditions": [{"field": "order_profit", "operator": "less_than", "value": "60"}]})
        details = self.match_details(rule, order([line_item(2, "20.00"), line_item(1, "15.00")]), True)
        assert (details["profit"]["profit"], details["profit"]["currency"], details["profit_conditions"]) == (
            55.0, "USD", [{"field": "order_profit", "operator": "less_than", "value": "60", "actual": 55.0}])

    def test_non_profit_rule_has_no_profit_details(self):
        rule = self.rule([{"field": "order_total", "operator": "greater_than", "value": "10"}])
        assert set(self.match_details(rule, order([line_item(1, "1.00")]), True)) == {"rule_name", "actions_successful"}
