from typing import Dict, List, Any, Union
import re
import logging
from datetime import datetime
from models import ProcessingRule

logger = logging.getLogger(__name__)

class RuleEngine:
    """Engine for evaluating and applying order processing rules"""
    
    def __init__(self):
        self.operators = {
            "equals": self._equals,
            "not_equals": self._not_equals,
            "greater_than": self._greater_than,
            "less_than": self._less_than,
            "greater_than_or_equal": self._greater_than_or_equal,
            "less_than_or_equal": self._less_than_or_equal,
            "contains": self._contains,
            "not_contains": self._not_contains,
            "starts_with": self._starts_with,
            "ends_with": self._ends_with,
            "in_list": self._in_list,
            "not_in_list": self._not_in_list,
            "regex_match": self._regex_match,
            "is_empty": self._is_empty,
            "is_not_empty": self._is_not_empty
        }
    
    def evaluate_rule(self, rule: ProcessingRule, order: Dict[str, Any]) -> bool:
        """Evaluate if a rule applies to an order"""
        try:
            conditions = rule.conditions
            if not conditions:
                return False
            
            # Get the logical operator (default to AND)
            logical_operator = "AND"
            if isinstance(conditions, dict) and "operator" in conditions:
                logical_operator = conditions.get("operator", "AND").upper()
                conditions = conditions.get("conditions", [])
            
            if not isinstance(conditions, list):
                logger.error(f"Invalid conditions format for rule {rule.id}")
                return False
            
            results = []
            for condition in conditions:
                result = self._evaluate_condition(condition, order)
                results.append(result)
            
            # Apply logical operator
            if logical_operator == "OR":
                return any(results)
            else:  # AND
                return all(results)
                
        except Exception as e:
            logger.error(f"Error evaluating rule {rule.id}: {str(e)}")
            return False
    
    def _evaluate_condition(self, condition: Dict[str, Any], order: Dict[str, Any]) -> bool:
        """Evaluate a single condition"""
        try:
            field = condition.get("field")
            operator = condition.get("operator")
            expected_value = condition.get("value")
            
            if not field or not operator:
                logger.error(f"Invalid condition: missing field or operator")
                return False
            
            # Get the actual value from the order
            actual_value = self._get_order_field_value(field, order)
            
            # Apply the operator
            if operator not in self.operators:
                logger.error(f"Unknown operator: {operator}")
                return False
            
            return self.operators[operator](actual_value, expected_value)
            
        except Exception as e:
            logger.error(f"Error evaluating condition: {str(e)}")
            return False
    
    def _get_order_field_value(self, field: str, order: Dict[str, Any]) -> Any:
        """Extract field value from order data"""
        try:
            # Handle nested field access with dot notation
            parts = field.split(".")
            value = order
            
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                elif isinstance(value, list) and part.isdigit():
                    index = int(part)
                    value = value[index] if index < len(value) else None
                else:
                    value = None
                    break
            
            # Handle special field mappings
            if field == "order_total":
                total_price = order.get("totalPriceSet", {}).get("shopMoney", {})
                return float(total_price.get("amount", 0))
            
            elif field == "order_weight":
                return float(order.get("totalWeight", 0))
            
            elif field == "shipping_province":
                shipping_addr = order.get("shippingAddress", {})
                return shipping_addr.get("province", "").strip().upper()
            
            elif field == "shipping_country":
                shipping_addr = order.get("shippingAddress", {})
                return shipping_addr.get("country", "").strip().upper()
            
            elif field == "shipping_city":
                shipping_addr = order.get("shippingAddress", {})
                return shipping_addr.get("city", "").strip()
            
            elif field == "shipping_method":
                shipping_lines = order.get("shippingLines", {}).get("edges", [])
                if shipping_lines:
                    return shipping_lines[0]["node"].get("title", "")
                return ""
            
            elif field == "customer_email":
                customer = order.get("customer", {})
                return customer.get("email", "") if customer else ""
            
            elif field == "order_tags":
                tags = order.get("tags", [])
                return tags if isinstance(tags, list) else tags.split(", ") if tags else []
            
            elif field == "product_types":
                product_types = set()
                line_items = order.get("lineItems", {}).get("edges", [])
                for item_edge in line_items:
                    product = item_edge["node"].get("product", {})
                    if product and product.get("productType"):
                        product_types.add(product["productType"])
                return list(product_types)
            
            elif field == "product_vendors":
                vendors = set()
                line_items = order.get("lineItems", {}).get("edges", [])
                for item_edge in line_items:
                    product = item_edge["node"].get("product", {})
                    if product and product.get("vendor"):
                        vendors.add(product["vendor"])
                return list(vendors)
            
            elif field == "product_skus":
                skus = []
                line_items = order.get("lineItems", {}).get("edges", [])
                for item_edge in line_items:
                    variant = item_edge["node"].get("variant", {})
                    if variant and variant.get("sku"):
                        skus.append(variant["sku"])
                return skus
            
            elif field == "order_created_at":
                created_at = order.get("createdAt")
                if created_at:
                    return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                return None
            
            elif field == "line_item_count":
                line_items = order.get("lineItems", {}).get("edges", [])
                return len(line_items)
            
            elif field == "total_quantity":
                total_qty = 0
                line_items = order.get("lineItems", {}).get("edges", [])
                for item_edge in line_items:
                    quantity = item_edge["node"].get("quantity", 0)
                    total_qty += quantity
                return total_qty
            
            return value
            
        except Exception as e:
            logger.error(f"Error getting field {field}: {str(e)}")
            return None
    
    # Operator implementations
    def _equals(self, actual: Any, expected: Any) -> bool:
        return actual == expected
    
    def _not_equals(self, actual: Any, expected: Any) -> bool:
        return actual != expected
    
    def _greater_than(self, actual: Any, expected: Any) -> bool:
        try:
            return float(actual) > float(expected)
        except (TypeError, ValueError):
            return False
    
    def _less_than(self, actual: Any, expected: Any) -> bool:
        try:
            return float(actual) < float(expected)
        except (TypeError, ValueError):
            return False
    
    def _greater_than_or_equal(self, actual: Any, expected: Any) -> bool:
        try:
            return float(actual) >= float(expected)
        except (TypeError, ValueError):
            return False
    
    def _less_than_or_equal(self, actual: Any, expected: Any) -> bool:
        try:
            return float(actual) <= float(expected)
        except (TypeError, ValueError):
            return False
    
    def _contains(self, actual: Any, expected: Any) -> bool:
        if actual is None:
            return False
        
        if isinstance(actual, list):
            return expected in actual
        
        return str(expected).lower() in str(actual).lower()
    
    def _not_contains(self, actual: Any, expected: Any) -> bool:
        return not self._contains(actual, expected)
    
    def _starts_with(self, actual: Any, expected: Any) -> bool:
        if actual is None:
            return False
        return str(actual).lower().startswith(str(expected).lower())
    
    def _ends_with(self, actual: Any, expected: Any) -> bool:
        if actual is None:
            return False
        return str(actual).lower().endswith(str(expected).lower())
    
    def _in_list(self, actual: Any, expected: List[Any]) -> bool:
        if not isinstance(expected, list):
            expected = [expected]
        return actual in expected
    
    def _not_in_list(self, actual: Any, expected: List[Any]) -> bool:
        return not self._in_list(actual, expected)
    
    def _regex_match(self, actual: Any, expected: str) -> bool:
        if actual is None:
            return False
        try:
            pattern = re.compile(expected, re.IGNORECASE)
            return bool(pattern.search(str(actual)))
        except re.error:
            logger.error(f"Invalid regex pattern: {expected}")
            return False
    
    def _is_empty(self, actual: Any, expected: Any) -> bool:
        if actual is None:
            return True
        if isinstance(actual, (list, dict, str)):
            return len(actual) == 0
        return False
    
    def _is_not_empty(self, actual: Any, expected: Any) -> bool:
        return not self._is_empty(actual, expected)

    def get_available_fields(self) -> List[Dict[str, str]]:
        """Get list of available order fields for rule creation"""
        return [
            {"field": "order_total", "label": "Order Total", "type": "number"},
            {"field": "order_weight", "label": "Total Weight (grams)", "type": "number"},
            {"field": "shipping_province", "label": "Shipping Province/State", "type": "string"},
            {"field": "shipping_country", "label": "Shipping Country", "type": "string"},
            {"field": "shipping_city", "label": "Shipping City", "type": "string"},
            {"field": "shipping_method", "label": "Shipping Method", "type": "string"},
            {"field": "customer_email", "label": "Customer Email", "type": "string"},
            {"field": "order_tags", "label": "Order Tags", "type": "array"},
            {"field": "product_types", "label": "Product Types", "type": "array"},
            {"field": "product_vendors", "label": "Product Vendors", "type": "array"},
            {"field": "product_skus", "label": "Product SKUs", "type": "array"},
            {"field": "order_created_at", "label": "Order Created Date", "type": "datetime"},
            {"field": "line_item_count", "label": "Number of Line Items", "type": "number"},
            {"field": "total_quantity", "label": "Total Quantity", "type": "number"},
        ]
    
    def get_available_operators(self) -> List[Dict[str, str]]:
        """Get list of available operators"""
        return [
            {"operator": "equals", "label": "Equals", "types": ["string", "number"]},
            {"operator": "not_equals", "label": "Not Equals", "types": ["string", "number"]},
            {"operator": "greater_than", "label": "Greater Than", "types": ["number"]},
            {"operator": "less_than", "label": "Less Than", "types": ["number"]},
            {"operator": "greater_than_or_equal", "label": "Greater Than or Equal", "types": ["number"]},
            {"operator": "less_than_or_equal", "label": "Less Than or Equal", "types": ["number"]},
            {"operator": "contains", "label": "Contains", "types": ["string", "array"]},
            {"operator": "not_contains", "label": "Does Not Contain", "types": ["string", "array"]},
            {"operator": "starts_with", "label": "Starts With", "types": ["string"]},
            {"operator": "ends_with", "label": "Ends With", "types": ["string"]},
            {"operator": "in_list", "label": "In List", "types": ["string", "number"]},
            {"operator": "not_in_list", "label": "Not In List", "types": ["string", "number"]},
            {"operator": "regex_match", "label": "Regex Match", "types": ["string"]},
            {"operator": "is_empty", "label": "Is Empty", "types": ["string", "array"]},
            {"operator": "is_not_empty", "label": "Is Not Empty", "types": ["string", "array"]},
        ]