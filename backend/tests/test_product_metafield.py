"""
Tests for the Product Metafield rule condition: validation, fetching metafield values
from Shopify, attaching them to orders and evaluating them. Pure — the GraphQL
transport is patched.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from rule_engine import RuleEngine
from schemas import RuleCondition, RuleCreate
from shopify_client import ShopifyClient
from tasks import LINE_ITEM_DEPENDENT_FIELDS, _ensure_product_metafields_for_rules, _rule_metafield_keys

KEY = "custom.weight"
PRODUCT_A = "gid://shopify/Product/1"
PRODUCT_B = "gid://shopify/Product/2"


def item(product_id, value, quantity=1, sku="SKU", key=KEY):
    product = None
    if product_id is not None:
        product = {"id": product_id}
        if value is not ...:
            product["metafieldValues"] = {key: value}
    return {"node": {"title": sku, "quantity": quantity, "product": product, "variant": {"sku": sku}}}


def order(*items):
    return {"name": "#1001", "lineItems": {"pageInfo": {"hasNextPage": False}, "edges": list(items)}}


def condition(operator, value, aggregate, key=KEY):
    return {"field": "product_metafield", "operator": operator, "value": value,
            "metafield": {"key": key, "aggregate": aggregate}}


def rule(*conditions, logic="AND"):
    return SimpleNamespace(id=1, name="metafield rule",
                           conditions={"operator": logic, "conditions": list(conditions)})


class TestMetafieldConditionEvaluation:
    def setup_method(self):
        self.engine = RuleEngine()

    def evaluate(self, cond, order_data, excluded_skus=None):
        return self.engine._evaluate_condition(cond, order_data, excluded_skus or [])

    @pytest.mark.parametrize("threshold,expected", [("6.9", True), ("7", False)])
    def test_sum_multiplies_by_quantity(self, threshold, expected):
        # 2 x 2.5 + 1 x 2 = 7
        data = order(item(PRODUCT_A, "2.5", quantity=2), item(PRODUCT_B, "2"))
        assert self.evaluate(condition("greater_than", threshold, "sum"), data) is expected

    def test_sum_skips_excluded_skus(self):
        data = order(item(PRODUCT_A, "3", sku="BOX-1"), item(PRODUCT_B, "10", sku="promo-insert"))
        assert self.evaluate(condition("equals", "3", "sum"), data, ["PROMO"]) is True

    def test_sum_counts_items_without_the_metafield_as_zero(self):
        data = order(item(PRODUCT_A, "4"), item(PRODUCT_B, None), item(None, ...))
        assert self.evaluate(condition("equals", "4", "sum"), data) is True

    @pytest.mark.parametrize("aggregate", ["sum", "max"])
    def test_no_values_at_all_is_empty(self, aggregate):
        data = order(item(PRODUCT_A, None), item(PRODUCT_B, ...))
        assert self.evaluate(condition("is_empty", "", aggregate), data) is True

    def test_max_takes_the_highest_item_value(self):
        data = order(item(PRODUCT_A, "2", quantity=10), item(PRODUCT_B, "5"))
        assert (self.evaluate(condition("equals", "5", "max"), data),
                self.evaluate(condition("greater_than", "5", "max"), data)) == (True, False)

    def test_any_matches_when_one_item_matches(self):
        data = order(item(PRODUCT_A, "1"), item(PRODUCT_B, "9"))
        assert (self.evaluate(condition("greater_than", "5", "any"), data),
                self.evaluate(condition("greater_than", "10", "any"), data)) == (True, False)

    def test_all_requires_every_item_to_match(self):
        data = order(item(PRODUCT_A, "6"), item(PRODUCT_B, "9"))
        assert (self.evaluate(condition("greater_than", "5", "all"), data),
                self.evaluate(condition("greater_than", "7", "all"), data)) == (True, False)

    def test_all_fails_when_an_item_has_no_value(self):
        data = order(item(PRODUCT_A, "6"), item(PRODUCT_B, None))
        assert self.evaluate(condition("greater_than", "5", "all"), data) is False

    def test_any_is_empty_flags_products_missing_the_metafield(self):
        complete = order(item(PRODUCT_A, "6"), item(PRODUCT_B, "1"))
        missing = order(item(PRODUCT_A, "6"), item(PRODUCT_B, None))
        assert (self.evaluate(condition("is_empty", "", "any"), complete),
                self.evaluate(condition("is_empty", "", "any"), missing)) == (False, True)

    def test_all_over_no_items_is_false(self):
        assert self.evaluate(condition("is_empty", "", "all"), order()) is False

    def test_text_values_compare_as_text(self):
        data = order(item(PRODUCT_A, "Hazmat", key="custom.class"), item(PRODUCT_B, "standard", key="custom.class"))
        assert (self.evaluate(condition("equals", "Hazmat", "any", key="custom.class"), data),
                self.evaluate(condition("equals", "Hazmat", "all", key="custom.class"), data)) == (True, False)

    def test_other_keys_are_ignored(self):
        data = order(item(PRODUCT_A, "8", key="custom.other"))
        assert self.evaluate(condition("is_empty", "", "sum"), data) is True

    def test_evaluate_rule_combines_with_other_conditions(self):
        data = order(item(PRODUCT_A, "3", quantity=2))
        data["totalPriceSet"] = {"shopMoney": {"amount": "50.00"}}
        matching = rule(condition("greater_than", "5", "sum"),
                        {"field": "order_total", "operator": "greater_than", "value": "40"})
        failing = rule(condition("greater_than", "6", "sum"),
                       {"field": "order_total", "operator": "greater_than", "value": "40"})
        assert (self.engine.evaluate_rule(matching, data), self.engine.evaluate_rule(failing, data)) == (True, False)

    def test_field_is_offered_to_the_rule_builder(self):
        assert {"field": "product_metafield", "label": "Product Metafield", "type": "metafield"} \
            in self.engine.get_available_fields()

    def test_standard_operators_apply_to_metafields(self):
        assert [op["operator"] for op in self.engine.get_available_operators() if "metafield" in op["types"]] == [
            "equals", "not_equals", "greater_than", "less_than", "greater_than_or_equal", "less_than_or_equal",
            "contains", "not_contains", "starts_with", "ends_with", "in_list", "not_in_list", "regex_match",
            "is_empty", "is_not_empty",
        ]

    def test_in_list_compares_numbers_numerically(self):
        data = order(item(PRODUCT_A, "5.0"))
        assert (self.evaluate(condition("in_list", ["4", "5"], "any"), data),
                self.evaluate(condition("not_in_list", ["4", "5"], "max"), data)) == (True, False)


class TestMetafieldConditionSchema:
    @pytest.mark.parametrize("key", ["custom.weight", "my_fields.item-weight", "$app:shipping.weight"])
    def test_accepts_valid_keys(self, key):
        cond = RuleCondition(**condition("greater_than", "5", "sum", key=key))
        assert cond.metafield.key == key

    @pytest.mark.parametrize("key", ["weight", "custom.", ".weight", "custom.weight.extra", "custom.we ight", "c.weight"])
    def test_rejects_invalid_keys(self, key):
        with pytest.raises(ValidationError):
            RuleCondition(**condition("greater_than", "5", "sum", key=key))

    def test_rejects_unknown_aggregate(self):
        with pytest.raises(ValidationError):
            RuleCondition(**condition("greater_than", "5", "average"))

    def test_metafield_options_are_required_for_the_field(self):
        with pytest.raises(ValidationError):
            RuleCondition(field="product_metafield", operator="greater_than", value="5")

    @pytest.mark.parametrize("conditions", [
        [condition("greater_than", "5", "max")],
        {"operator": "AND", "conditions": [condition("greater_than", "5", "max")]},
    ])
    def test_options_are_kept_when_the_rule_is_saved(self, conditions):
        created = RuleCreate(name="Heavy", conditions=conditions,
                             actions=[{"type": "add_tag", "parameters": {"tag": "heavy"}}])
        # Same conversion the rules router applies before storing
        saved = created.conditions.dict() if hasattr(created.conditions, "dict") else created.conditions
        assert saved["conditions"][0]["metafield"] == {"key": KEY, "aggregate": "max"}


def metafield_response(nodes):
    return {"data": {"nodes": nodes}}


class TestGetProductMetafields:
    def setup_method(self):
        self.client = ShopifyClient("test-store.myshopify.com", "test_token")

    def run(self, product_ids, keys, responder):
        calls = []

        async def fake_request(query, variables=None, retry_count=3):
            calls.append((query, variables))
            return responder(variables)

        with patch.object(self.client, "_make_graphql_request", side_effect=fake_request):
            result = asyncio.run(self.client.get_product_metafields(product_ids, keys))
        return result, calls

    def test_maps_aliases_back_to_keys(self):
        def responder(variables):
            return metafield_response([
                {"id": PRODUCT_A, "m0": {"value": "2.5", "type": "number_decimal"}, "m1": None},
                None,
            ])

        result, _ = self.run([PRODUCT_A, PRODUCT_B], [KEY, "custom.class"], responder)
        assert result == {PRODUCT_A: {KEY: "2.5", "custom.class": None},
                          PRODUCT_B: {KEY: None, "custom.class": None}}

    def test_keys_are_sent_as_variables(self):
        _, calls = self.run([PRODUCT_A], [KEY], lambda v: metafield_response([{"id": PRODUCT_A, "m0": None}]))
        query, variables = calls[0]
        assert (variables, "custom" in query, "weight" in query) == (
            {"ids": [PRODUCT_A], "ns0": "custom", "k0": "weight"}, False, False)

    def test_batches_one_hundred_ids_per_request(self):
        ids = [f"gid://shopify/Product/{i}" for i in range(250)]

        def responder(variables):
            return metafield_response([{"id": pid, "m0": {"value": "1"}} for pid in variables["ids"]])

        result, calls = self.run(ids, [KEY], responder)
        assert ([len(v["ids"]) for _, v in calls], len(result)) == ([100, 100, 50], 250)

    def test_nothing_to_fetch_makes_no_request(self):
        result, calls = self.run([], [KEY], lambda v: None)
        assert (result, calls) == ({}, [])


class TestEnsureProductMetafields:
    def test_attaches_values_and_fetches_each_product_once_per_sync(self):
        client = ShopifyClient("test-store.myshopify.com", "test_token")
        requested = []

        async def fake_fetch(product_ids, keys):
            requested.append(sorted(product_ids))
            return {pid: {KEY: "1.5" if pid == PRODUCT_A else "4"} for pid in product_ids}

        first = order(item(PRODUCT_A, ...), item(PRODUCT_A, ...), item(None, ...))
        second = order(item(PRODUCT_A, ...), item(PRODUCT_B, ...))
        cache = {}
        with patch.object(client, "get_product_metafields", side_effect=fake_fetch):
            asyncio.run(_ensure_product_metafields_for_rules(client, first, {KEY}, cache))
            asyncio.run(_ensure_product_metafields_for_rules(client, second, {KEY}, cache))

        values = [(e["node"]["product"] or {}).get("metafieldValues")
                  for o in (first, second) for e in o["lineItems"]["edges"]]
        assert (requested, values) == (
            [[PRODUCT_A], [PRODUCT_B]],
            [{KEY: "1.5"}, {KEY: "1.5"}, None, {KEY: "1.5"}, {KEY: "4"}],
        )

    def test_fetch_failure_leaves_values_missing(self):
        client = ShopifyClient("test-store.myshopify.com", "test_token")
        data = order(item(PRODUCT_A, ...))
        with patch.object(client, "get_product_metafields", side_effect=RuntimeError("boom")):
            asyncio.run(_ensure_product_metafields_for_rules(client, data, {KEY}, {}))
        assert "metafieldValues" not in data["lineItems"]["edges"][0]["node"]["product"]

    def test_no_keys_makes_no_request(self):
        client = ShopifyClient("test-store.myshopify.com", "test_token")
        with patch.object(client, "get_product_metafields") as fetch:
            asyncio.run(_ensure_product_metafields_for_rules(client, order(item(PRODUCT_A, ...)), set(), {}))
        assert fetch.call_count == 0


class TestRuleMetafieldKeys:
    def test_collects_keys_from_metafield_conditions_only(self):
        rules = [
            rule(condition("greater_than", "5", "sum"), {"field": "order_total", "operator": "greater_than", "value": "1"}),
            rule(condition("equals", "x", "any", key="custom.class")),
            SimpleNamespace(conditions=[{"field": "product_metafield", "operator": "equals", "value": "1"}]),
        ]
        assert _rule_metafield_keys(rules) == {KEY, "custom.class"}

    def test_field_needs_every_line_item(self):
        assert "product_metafield" in LINE_ITEM_DEPENDENT_FIELDS
