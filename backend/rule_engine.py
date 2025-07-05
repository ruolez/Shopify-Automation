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
    
    def evaluate_rule(self, rule: ProcessingRule, order: Dict[str, Any], excluded_skus: List[str] = None) -> bool:
        """Evaluate if a rule applies to an order"""
        try:
            order_name = order.get("name", "unknown")
            logger.info(f"Evaluating rule '{rule.name}' for order {order_name}")
            
            conditions_data = rule.conditions
            if not conditions_data:
                return False
            
            # Handle both legacy array format and new object format
            logical_operator = "AND"
            conditions_list = []
            
            if isinstance(conditions_data, list):
                # Legacy format: direct list of conditions (default to AND)
                conditions_list = conditions_data
                logical_operator = "AND"
                logger.info(f"  Using legacy format with implicit AND operator")
            elif isinstance(conditions_data, dict):
                # New format: object with operator and conditions
                logical_operator = conditions_data.get("operator", "AND").upper()
                conditions_list = conditions_data.get("conditions", [])
                logger.info(f"  Using new format with {logical_operator} operator")
            else:
                logger.error(f"Invalid conditions format for rule {rule.id}: {type(conditions_data)}")
                return False
            
            if not isinstance(conditions_list, list):
                logger.error(f"Conditions must be a list, got {type(conditions_list)} for rule {rule.id}")
                return False
            
            if not conditions_list:
                logger.warning(f"No conditions found for rule {rule.id}")
                return False
            
            # Evaluate each condition
            results = []
            for i, condition in enumerate(conditions_list):
                result = self._evaluate_condition(condition, order, excluded_skus)
                results.append(result)
                logger.info(f"  Condition {i+1} ({condition.get('field', 'unknown')} {condition.get('operator', 'unknown')} {condition.get('value', 'unknown')}): {result}")
            
            # Apply logical operator
            if logical_operator == "OR":
                final_result = any(results)
                logger.info(f"  Applying OR logic: any({results}) = {final_result}")
            else:  # AND
                final_result = all(results)
                logger.info(f"  Applying AND logic: all({results}) = {final_result}")
                
            logger.info(f"Rule '{rule.name}' evaluation for order {order_name}: {final_result}")
            return final_result
                
        except Exception as e:
            logger.error(f"Error evaluating rule {rule.id}: {str(e)}", exc_info=True)
            return False
    
    def _evaluate_condition(self, condition: Dict[str, Any], order: Dict[str, Any], excluded_skus: List[str] = None) -> bool:
        """Evaluate a single condition"""
        try:
            field = condition.get("field")
            operator = condition.get("operator")
            expected_value = condition.get("value")
            
            if not field or not operator:
                logger.error(f"Invalid condition: missing field or operator")
                return False
            
            # Get the actual value from the order
            actual_value = self._get_order_field_value(field, order, excluded_skus)
            
            # Convert expected value to uppercase for province/state/country fields to make comparison case-insensitive
            if field in ["shipping_province", "shipping_country", "billing_province", "billing_country"]:
                if isinstance(expected_value, str):
                    expected_value = expected_value.upper()
                elif isinstance(expected_value, list):
                    # Convert all list items to uppercase for case-insensitive comparison
                    expected_value = [str(item).upper() for item in expected_value]
            
            # Apply the operator
            if operator not in self.operators:
                logger.error(f"Unknown operator: {operator}")
                return False
            
            return self.operators[operator](actual_value, expected_value)
            
        except Exception as e:
            logger.error(f"Error evaluating condition: {str(e)}")
            return False
    
    def _get_order_field_value(self, field: str, order: Dict[str, Any], excluded_skus: List[str] = None) -> Any:
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
                # Shopify returns weight in grams via currentTotalWeight field
                weight_grams = order.get("currentTotalWeight", 0)
                if weight_grams is None or weight_grams == "":
                    logger.info(f"Order {order.get('name', 'unknown')}: No weight data available")
                    return 0
                weight_grams = float(weight_grams)
                
                # Calculate weight from individual line items, excluding specified SKUs
                line_items = order.get("lineItems", {}).get("edges", [])
                total_calculated_weight = 0
                excluded_skus = excluded_skus or []
                excluded_count = 0
                
                logger.info(f"Order {order.get('name', 'unknown')}: Calculating weight (excluding {len(excluded_skus)} SKU patterns)")
                
                for item_edge in line_items:
                    item = item_edge["node"]
                    variant = item.get("variant", {})
                    sku = variant.get("sku", "")
                    
                    # Check if this SKU should be excluded
                    skip_item = False
                    if sku and excluded_skus:
                        for excluded_pattern in excluded_skus:
                            if excluded_pattern.lower() in sku.lower():
                                skip_item = True
                                excluded_count += 1
                                logger.info(f"  - EXCLUDED: {item.get('title', 'Unknown')} (SKU: {sku}) matches pattern '{excluded_pattern}'")
                                break
                    
                    if skip_item:
                        continue
                    
                    quantity = item.get("quantity", 0)
                    inventory_item = variant.get("inventoryItem", {})
                    measurement = inventory_item.get("measurement", {})
                    weight_obj = measurement.get("weight", {})
                    
                    item_weight_value = weight_obj.get("value", 0) if weight_obj else 0
                    item_weight_unit = weight_obj.get("unit", "GRAMS") if weight_obj else "GRAMS"
                    
                    # Convert to grams if needed
                    if item_weight_unit == "POUNDS":
                        item_weight_grams = float(item_weight_value) * 453.592
                    elif item_weight_unit == "OUNCES":
                        item_weight_grams = float(item_weight_value) * 28.3495
                    elif item_weight_unit == "KILOGRAMS":
                        item_weight_grams = float(item_weight_value) * 1000
                    else:  # GRAMS
                        item_weight_grams = float(item_weight_value)
                    
                    total_item_weight = item_weight_grams * quantity
                    total_calculated_weight += total_item_weight
                    
                    logger.info(f"  - {item.get('title', 'Unknown')} (SKU: {sku}): {quantity} x {item_weight_value} {item_weight_unit} = {total_item_weight}g")
                
                if excluded_count > 0:
                    logger.info(f"Order {order.get('name', 'unknown')}: Excluded {excluded_count} items from weight calculation")
                
                logger.info(f"Order {order.get('name', 'unknown')}: Shopify currentTotalWeight = {weight_grams}g")
                logger.info(f"Order {order.get('name', 'unknown')}: Calculated from included line items = {total_calculated_weight}g")
                
                # When SKUs are excluded, always use calculated weight instead of Shopify's total
                if excluded_skus and excluded_count > 0:
                    logger.info(f"Order {order.get('name', 'unknown')}: Using calculated weight due to SKU exclusions")
                    return total_calculated_weight
                
                # Use calculated weight if it's significantly different from Shopify's value
                # This handles cases where Shopify's currentTotalWeight is incorrect
                if abs(total_calculated_weight - weight_grams) > 1:  # More than 1g difference
                    logger.warning(f"Order {order.get('name', 'unknown')}: Large discrepancy between Shopify currentTotalWeight ({weight_grams}g) and calculated weight ({total_calculated_weight}g). Using calculated weight.")
                    return total_calculated_weight
                
                return weight_grams
            
            elif field == "shipping_province":
                shipping_addr = order.get("shippingAddress", {})
                province = shipping_addr.get("province", "").strip()
                logger.info(f"Order {order.get('name', 'unknown')}: Raw shipping province = '{province}', Uppercase = '{province.upper()}'")
                return province.upper()
            
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