"""
Tests for the shipping-cost estimate used in Order Profit. Pure — no database,
no MS SQL; DB-touching functions are exercised through patched collaborators.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import shipping_estimate_service as svc
from rule_engine import RuleEngine, calculate_order_profit, PROFIT_FIELDS
from shipper_db import PARCEL_COSTS_SQL, ParcelCost, ShipperDbConfig, parcel_costs_from_rows
from tests.test_order_profit import line_item, order


def sample(weight, cost):
    return (float(weight), float(cost))


class TestPickSamples:
    def test_tight_tier_wins_when_it_has_enough(self):
        samples = [sample(100, 5), sample(105, 6), sample(110, 7), sample(140, 20)]
        assert svc.pick_samples(samples, 100.0) == (10, [5.0, 6.0, 7.0])

    def test_widens_to_next_tier_when_short(self):
        samples = [sample(100, 5), sample(105, 6), sample(120, 9), sample(140, 20)]
        assert svc.pick_samples(samples, 100.0) == (25, [5.0, 6.0, 9.0])

    def test_widens_to_100g_when_50g_has_too_few(self):
        samples = [sample(60, 4), sample(145, 8), sample(190, 11)]
        assert svc.pick_samples(samples, 100.0) == (100, [4.0, 8.0, 11.0])

    def test_uses_widest_tier_even_with_fewer_than_minimum(self):
        samples = [sample(60, 4), sample(195, 8)]
        assert svc.pick_samples(samples, 100.0) == (100, [4.0, 8.0])

    def test_no_samples_within_widest_tier(self):
        assert svc.pick_samples([sample(250, 9)], 100.0) == (None, [])

    def test_boundary_is_inclusive(self):
        samples = [sample(90, 1), sample(110, 2), sample(100, 3)]
        assert svc.pick_samples(samples, 100.0) == (10, [1.0, 2.0, 3.0])


class TestEstimateFromSamples:
    def test_average_rounded_to_cents(self):
        samples = [sample(100, 5.10), sample(101, 5.25), sample(99, 5.33)]
        assert svc.estimate_from_samples(samples, 100.0) == {"cost": 5.23, "samples": 3, "tolerance_g": 10}

    def test_no_match_gives_no_estimate(self):
        assert svc.estimate_from_samples([], 100.0) == {"cost": None, "samples": 0, "tolerance_g": None}


class TestOrderShippingState:
    @pytest.mark.parametrize("province,expected", [("California", "CALIFORNIA"), ("  Texas ", "TEXAS"), ("", None), (None, None)])
    def test_uppercases_shopify_province(self, province, expected):
        assert svc.order_shipping_state({"shippingAddress": {"province": province}}) == expected

    def test_missing_address(self):
        assert svc.order_shipping_state({"shippingAddress": None}) is None


class TestCalculateOrderProfitWithShipping:
    def test_shipping_is_deducted_from_profit_and_margin(self):
        result = calculate_order_profit(order([line_item(2, "20.00"), line_item(1, "15.00")]), shipping_cost=7.5)
        assert (result["profit"], result["margin_percent"], result["shipping_cost"]) == (47.5, pytest.approx(43.18), 7.5)

    def test_without_shipping_is_unchanged_and_reports_none(self):
        result = calculate_order_profit(order([line_item(2, "20.00"), line_item(1, "15.00")]))
        assert (result["profit"], result["shipping_cost"]) == (55.0, None)

    def test_unknown_profit_keeps_shipping_key(self):
        result = calculate_order_profit(order([line_item(1, "1.00")], has_next_page=True), shipping_cost=5.0)
        assert (result["profit"], result["shipping_cost"], result["truncated"]) == (None, None, True)


class TestResolveShippingCost:
    def setup_method(self):
        self.store = SimpleNamespace(id=7, user_id=3)
        self.db = Mock()

    def test_estimate_is_used_when_available(self):
        with patch.object(svc, "estimate_shipping_cost", return_value={"cost": 6.4, "samples": 4, "tolerance_g": 25}) as est:
            info = svc.resolve_shipping_cost(self.db, self.store, order([line_item(1, "1.00")]), settings=SimpleNamespace(default_shipping_amount=9))
        assert (info["shipping_cost"], info["source"], info["samples"], info["tolerance_g"]) == (6.4, "estimate", 4, 25)
        assert est.call_args.args[:2] == (self.db, 7)

    def test_default_amount_when_no_estimate(self):
        with patch.object(svc, "estimate_shipping_cost", return_value=dict(svc.NO_ESTIMATE)):
            info = svc.resolve_shipping_cost(self.db, self.store, order([line_item(1, "1.00")]), settings=SimpleNamespace(default_shipping_amount=Decimal("8.50")))
        assert (info["shipping_cost"], info["source"], info["samples"]) == (8.5, "default", 0)

    def test_no_default_means_nothing_deducted(self):
        with patch.object(svc, "estimate_shipping_cost", return_value=dict(svc.NO_ESTIMATE)):
            info = svc.resolve_shipping_cost(self.db, self.store, order([line_item(1, "1.00")]), settings=SimpleNamespace(default_shipping_amount=0))
        assert (info["shipping_cost"], info["source"]) == (None, "none")

    def test_state_and_weight_are_passed_to_the_estimate(self):
        data = order([line_item(1, "1.00")])
        data["shippingAddress"] = {"province": "Ohio"}
        data["currentTotalWeight"] = 250
        data["lineItems"]["edges"][0]["node"]["variant"]["inventoryItem"]["measurement"] = {"weight": {"value": 250, "unit": "GRAMS"}}
        with patch.object(svc, "estimate_shipping_cost", return_value=dict(svc.NO_ESTIMATE)) as est:
            info = svc.resolve_shipping_cost(self.db, self.store, data, settings=SimpleNamespace(default_shipping_amount=0))
        assert est.call_args.args[2:4] == ("OHIO", 250.0)
        assert (info["shipping_state"], info["weight_grams"]) == ("OHIO", 250.0)


class TestEstimateShippingCostGuards:
    @pytest.mark.parametrize("state,weight", [(None, 100.0), ("OHIO", None), ("OHIO", 0.0)])
    def test_missing_inputs_skip_the_query(self, state, weight):
        db = Mock()
        assert svc.estimate_shipping_cost(db, 1, state, weight) == dict(svc.NO_ESTIMATE)
        assert db.query.call_count == 0


class TestProfitWithShippingViaEngine:
    def test_engine_without_store_context_ignores_shipping(self):
        engine = RuleEngine()
        data = order([line_item(2, "20.00"), line_item(1, "15.00")])
        assert engine._get_order_field_value("order_profit", data) == 55.0
        assert engine._get_order_field_value("shipping_estimate_samples", data) == 0
        assert engine._get_order_field_value("estimated_shipping_cost", data) is None

    def test_engine_with_store_context_uses_estimate_and_memoizes(self):
        engine = RuleEngine()
        data = order([line_item(2, "20.00"), line_item(1, "15.00")])
        data["id"] = "gid://shopify/Order/1"
        store = SimpleNamespace(id=7, user_id=3)
        info = {"shipping_cost": 5.0, "source": "estimate", "samples": 3, "tolerance_g": 10, "shipping_state": "OHIO", "weight_grams": 100.0}
        with patch.object(svc, "resolve_shipping_cost", return_value=info) as resolve:
            values = {field: engine._get_order_field_value(field, data, [], store) for field in PROFIT_FIELDS}
        assert values == {
            "order_profit": 50.0,
            "order_profit_margin": pytest.approx(45.45),
            "line_items_missing_cost": 0,
            "estimated_shipping_cost": 5.0,
            "shipping_estimate_samples": 3,
        }
        assert resolve.call_count == 1

    def test_estimate_failure_falls_back_to_profit_without_shipping(self):
        engine = RuleEngine(db_session=Mock())
        data = order([line_item(2, "20.00"), line_item(1, "15.00")])
        with patch.object(svc, "resolve_shipping_cost", side_effect=RuntimeError("db down")):
            assert engine._get_order_field_value("order_profit", data, [], SimpleNamespace(id=7, user_id=3)) == 55.0

    def test_schema_exposes_new_fields_as_numbers(self):
        fields = {f["field"]: f["type"] for f in RuleEngine().get_available_fields()}
        assert (fields["estimated_shipping_cost"], fields["shipping_estimate_samples"]) == ("number", "number")


class TestBuildSamples:
    def raw(self, weight_grams, province="Ohio"):
        item = {"node": {"title": "[REDACTED]", "quantity": 1, "variant": {"sku": "ITEM-1", "inventoryItem": {
            "measurement": {"weight": {"value": weight_grams, "unit": "GRAMS"}}}}}}
        return {"name": "[REDACTED]", "currentTotalWeight": weight_grams, "shippingAddress": {"province": province},
                "lineItems": {"edges": [item] if weight_grams else []}}

    def test_joins_by_order_name_column_not_redacted_raw_name(self):
        candidates = [svc.Candidate("#1001", "OHIO", self.raw(120)), svc.Candidate("#1002", "OHIO", self.raw(300))]
        parcel_costs = {"#1001": ParcelCost(7.25, 2, date(2026, 8, 20))}
        samples = svc.build_samples(candidates, parcel_costs, [], store_id=7, user_id=3)
        assert samples == [{
            "user_id": 3, "store_id": 7, "order_name": "#1001", "shipping_state": "OHIO",
            "weight_grams": 120.0, "shipping_cost": 7.25, "parcel_count": 2, "shipped_at": date(2026, 8, 20),
        }]

    def test_archive_json_text_is_parsed(self):
        import json
        candidates = [svc.Candidate("#1001", "ohio ", json.dumps(self.raw(120)))]
        samples = svc.build_samples(candidates, {"#1001": ParcelCost(5.0, 1, date(2026, 8, 20))}, [], store_id=7, user_id=3)
        assert (samples[0]["shipping_state"], samples[0]["weight_grams"]) == ("OHIO", 120.0)

    @pytest.mark.parametrize("state,weight", [("", 120), (None, 120), ("OHIO", 0), ("OHIO", None)])
    def test_skips_samples_without_state_or_weight(self, state, weight):
        candidates = [svc.Candidate("#1001", state, self.raw(weight))]
        assert svc.build_samples(candidates, {"#1001": ParcelCost(5.0, 1, date(2026, 8, 20))}, [], store_id=7, user_id=3) == []

    def test_excluded_skus_reduce_sample_weight(self):
        raw = {
            "currentTotalWeight": 500, "shippingAddress": {"province": "Ohio"},
            "lineItems": {"edges": [
                {"node": {"quantity": 1, "variant": {"sku": "BOX-1", "inventoryItem": {"measurement": {"weight": {"value": 400, "unit": "GRAMS"}}}}}},
                {"node": {"quantity": 1, "variant": {"sku": "ITEM-1", "inventoryItem": {"measurement": {"weight": {"value": 100, "unit": "GRAMS"}}}}}},
            ]},
        }
        samples = svc.build_samples([svc.Candidate("#1001", "OHIO", raw)], {"#1001": ParcelCost(5.0, 1, date(2026, 8, 20))}, ["BOX"], store_id=7, user_id=3)
        assert samples[0]["weight_grams"] == 100.0


class TestParcelCosts:
    def test_rows_are_aggregated_into_parcel_costs(self):
        rows = [
            {"order_number": " #1001 ", "total_cost": Decimal("12.50"), "parcel_count": 2, "null_cost_count": 0, "last_ship_date": date(2026, 8, 20)},
            {"order_number": "#1002", "total_cost": Decimal("4.00"), "parcel_count": 1, "null_cost_count": 1, "last_ship_date": date(2026, 8, 21)},
            {"order_number": "#1003", "total_cost": None, "parcel_count": 1, "null_cost_count": 1, "last_ship_date": None},
            {"order_number": "", "total_cost": Decimal("1.00"), "parcel_count": 1, "null_cost_count": 0, "last_ship_date": None},
        ]
        assert parcel_costs_from_rows(rows) == {"#1001": ParcelCost(12.5, 2, date(2026, 8, 20))}

    def test_sql_excludes_unshipped_parcels_and_groups_by_order(self):
        assert ("tracking_number IS NOT NULL" in PARCEL_COSTS_SQL and "NOT IN (4, 9, 10)" in PARCEL_COSTS_SQL
                and "GROUP BY p.order_number" in PARCEL_COSTS_SQL and PARCEL_COSTS_SQL.count("%s") == 1)

    def test_config_requires_host_database_and_user(self):
        full = SimpleNamespace(shipper_db_host=" sql.local ", shipper_db_port=None, shipper_db_name="shipper", shipper_db_user="ro", shipper_db_password="pw")
        assert ShipperDbConfig.from_settings(full) == ShipperDbConfig("sql.local", 1433, "shipper", "ro", "pw")
        assert ShipperDbConfig.from_settings(SimpleNamespace(shipper_db_host="sql.local", shipper_db_name=None, shipper_db_user="ro")) is None


class TestDescribePymssqlError:
    def test_nested_tuple_with_bytes_message_is_flattened(self):
        from shipper_db import _describe
        exc = Exception((20009, b"DB-Lib error message 20009, severity 9:\nUnable to connect: Adaptive Server is unavailable (127.0.0.1)\n"))
        assert _describe(exc) == "DB-Lib error message 20009, severity 9: Unable to connect: Adaptive Server is unavailable (127.0.0.1)"

    def test_plain_exception_text(self):
        from shipper_db import _describe
        assert _describe(RuntimeError("login failed")) == "login failed"
