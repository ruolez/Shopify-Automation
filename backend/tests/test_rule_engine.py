import pytest
from rule_engine import RuleEngine

class TestRuleEngine:
    def setup_method(self):
        """Set up test fixtures"""
        self.rule_engine = RuleEngine()
        
        # Sample Shopify order data
        self.sample_order = {
            "id": "gid://shopify/Order/12345",
            "name": "#1001",
            "totalPriceSet": {
                "shopMoney": {
                    "amount": "150.00",
                    "currencyCode": "USD"
                }
            },
            "totalWeightGrams": 1500,
            "shippingAddress": {
                "provinceCode": "CA",
                "countryCode": "US"
            },
            "shippingLines": {
                "nodes": [
                    {
                        "title": "Standard Shipping",
                        "code": "standard"
                    }
                ]
            },
            "tags": ["priority", "vip"],
            "lineItems": {
                "nodes": [
                    {
                        "quantity": 2,
                        "product": {
                            "productType": "Electronics"
                        }
                    }
                ]
            }
        }

    def test_extract_order_total(self):
        """Test extracting order total from Shopify order"""
        result = self.rule_engine.extract_field_value(self.sample_order, "order_total")
        assert result == 150.0

    def test_extract_order_weight(self):
        """Test extracting order weight"""
        result = self.rule_engine.extract_field_value(self.sample_order, "order_weight")
        assert result == 1500

    def test_extract_shipping_state(self):
        """Test extracting shipping state"""
        result = self.rule_engine.extract_field_value(self.sample_order, "shipping_state")
        assert result == "CA"

    def test_extract_shipping_country(self):
        """Test extracting shipping country"""
        result = self.rule_engine.extract_field_value(self.sample_order, "shipping_country")
        assert result == "US"

    def test_extract_shipping_method(self):
        """Test extracting shipping method"""
        result = self.rule_engine.extract_field_value(self.sample_order, "shipping_method")
        assert result == "Standard Shipping"

    def test_extract_order_tags(self):
        """Test extracting order tags"""
        result = self.rule_engine.extract_field_value(self.sample_order, "order_tags")
        assert result == ["priority", "vip"]

    def test_extract_item_count(self):
        """Test extracting item count"""
        result = self.rule_engine.extract_field_value(self.sample_order, "item_count")
        assert result == 2

    def test_extract_product_type(self):
        """Test extracting product type"""
        result = self.rule_engine.extract_field_value(self.sample_order, "product_type")
        assert result == "Electronics"

    def test_evaluate_condition_equals(self):
        """Test equals operator"""
        condition = {
            "field": "shipping_state",
            "operator": "equals",
            "value": "CA"
        }
        result = self.rule_engine.evaluate_condition(condition, self.sample_order)
        assert result is True

    def test_evaluate_condition_not_equals(self):
        """Test not_equals operator"""
        condition = {
            "field": "shipping_state",
            "operator": "not_equals",
            "value": "NY"
        }
        result = self.rule_engine.evaluate_condition(condition, self.sample_order)
        assert result is True

    def test_evaluate_condition_greater_than(self):
        """Test greater_than operator"""
        condition = {
            "field": "order_total",
            "operator": "greater_than",
            "value": "100"
        }
        result = self.rule_engine.evaluate_condition(condition, self.sample_order)
        assert result is True

    def test_evaluate_condition_less_than(self):
        """Test less_than operator"""
        condition = {
            "field": "order_total",
            "operator": "less_than",
            "value": "200"
        }
        result = self.rule_engine.evaluate_condition(condition, self.sample_order)
        assert result is True

    def test_evaluate_condition_contains(self):
        """Test contains operator"""
        condition = {
            "field": "order_tags",
            "operator": "contains",
            "value": "vip"
        }
        result = self.rule_engine.evaluate_condition(condition, self.sample_order)
        assert result is True

    def test_evaluate_condition_not_contains(self):
        """Test not_contains operator"""
        condition = {
            "field": "order_tags",
            "operator": "not_contains",
            "value": "bulk"
        }
        result = self.rule_engine.evaluate_condition(condition, self.sample_order)
        assert result is True

    def test_evaluate_condition_in(self):
        """Test in operator"""
        condition = {
            "field": "shipping_state",
            "operator": "in",
            "value": ["CA", "NY", "TX"]
        }
        result = self.rule_engine.evaluate_condition(condition, self.sample_order)
        assert result is True

    def test_evaluate_condition_not_in(self):
        """Test not_in operator"""
        condition = {
            "field": "shipping_state",
            "operator": "not_in",
            "value": ["FL", "AZ"]
        }
        result = self.rule_engine.evaluate_condition(condition, self.sample_order)
        assert result is True

    def test_evaluate_rule_all_conditions_true(self):
        """Test rule evaluation when all conditions are true"""
        rule = {
            "conditions": [
                {
                    "field": "order_total",
                    "operator": "greater_than",
                    "value": "100"
                },
                {
                    "field": "shipping_state",
                    "operator": "equals",
                    "value": "CA"
                }
            ]
        }
        result = self.rule_engine.evaluate_rule(rule, self.sample_order)
        assert result is True

    def test_evaluate_rule_some_conditions_false(self):
        """Test rule evaluation when some conditions are false"""
        rule = {
            "conditions": [
                {
                    "field": "order_total",
                    "operator": "greater_than",
                    "value": "100"
                },
                {
                    "field": "shipping_state",
                    "operator": "equals",
                    "value": "NY"
                }
            ]
        }
        result = self.rule_engine.evaluate_rule(rule, self.sample_order)
        assert result is False

    def test_evaluate_rule_empty_conditions(self):
        """Test rule evaluation with empty conditions"""
        rule = {"conditions": []}
        result = self.rule_engine.evaluate_rule(rule, self.sample_order)
        assert result is True  # Empty conditions should default to True

    def test_invalid_field_extraction(self):
        """Test field extraction with invalid field"""
        result = self.rule_engine.extract_field_value(self.sample_order, "invalid_field")
        assert result is None

    def test_invalid_operator(self):
        """Test condition evaluation with invalid operator"""
        condition = {
            "field": "order_total",
            "operator": "invalid_operator",
            "value": "100"
        }
        result = self.rule_engine.evaluate_condition(condition, self.sample_order)
        assert result is False