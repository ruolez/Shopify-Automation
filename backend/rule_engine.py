from typing import Dict, List, Any, Union, Optional
from datetime import datetime
from decimal import Decimal
from models import ProcessingRule, FraudAnalysis
from sqlalchemy.orm import Session
from safe_regex import safe_regex_match
from logging_config import get_logger, debug_log, DEBUG_LOGGING

logger = get_logger(__name__)

PROFIT_FIELDS = ("order_profit", "order_profit_margin", "line_items_missing_cost")

_UNKNOWN_PROFIT = {
    "revenue": None,
    "product_cost": None,
    "profit": None,
    "margin_percent": None,
    "missing_cost_count": None,
    "truncated": False,
}


def _shop_money_amount(money_set: Any) -> Optional[float]:
    amount = ((money_set or {}).get("shopMoney") or {}).get("amount")
    if amount in (None, ""):
        return None
    return float(amount)


def calculate_order_profit(order: Dict[str, Any]) -> Dict[str, Any]:
    """Order profit from a raw Shopify GraphQL order dict, in shop currency.

    revenue      = currentSubtotalPriceSet + currentShippingPriceSet
                   (minus currentTotalTaxSet when the store prices tax-inclusive)
    product_cost = sum(currentQuantity x variant.inventoryItem.unitCost)
    profit       = revenue - product_cost

    Real shipping cost is not included yet. Line items without a unit cost count as
    $0 and are reported in missing_cost_count. Gift cards and tips/fees (no variant,
    not shippable) have no cost and are not counted as missing. When the line-item
    connection is truncated the cost would be partial, so every value is None.
    """
    order_name = order.get("name", "unknown")
    subtotal_set = order.get("currentSubtotalPriceSet")
    subtotal = _shop_money_amount(subtotal_set)
    if subtotal is None:
        debug_log(logger, f"Order {order_name}: no currentSubtotalPriceSet in payload, profit unknown")
        return dict(_UNKNOWN_PROFIT)

    line_items_conn = order.get("lineItems") or {}
    if (line_items_conn.get("pageInfo") or {}).get("hasNextPage"):
        logger.warning(
            f"Order {order_name}: line items truncated by page size — "
            f"product cost would be partial, profit unknown"
        )
        return {**_UNKNOWN_PROFIT, "truncated": True}

    revenue = subtotal + (_shop_money_amount(order.get("currentShippingPriceSet")) or 0.0)
    if order.get("taxesIncluded"):
        revenue -= _shop_money_amount(order.get("currentTotalTaxSet")) or 0.0
    order_currency = ((subtotal_set or {}).get("shopMoney") or {}).get("currencyCode")

    product_cost = 0.0
    missing_cost_count = 0
    for edge in line_items_conn.get("edges") or []:
        item = (edge or {}).get("node") or {}
        quantity = item.get("currentQuantity")
        if quantity is None:
            quantity = item.get("quantity") or 0
        if quantity <= 0:
            continue
        if (item.get("product") or {}).get("isGiftCard"):
            continue
        variant = item.get("variant")
        if variant is None:
            if item.get("requiresShipping") is False:
                continue
            missing_cost_count += 1
            debug_log(logger, f"  - {item.get('title', 'Unknown')}: no variant (deleted product), cost unknown")
            continue
        unit_cost = (variant.get("inventoryItem") or {}).get("unitCost") or {}
        if unit_cost.get("amount") in (None, ""):
            missing_cost_count += 1
            debug_log(logger, f"  - {item.get('title', 'Unknown')} (SKU: {variant.get('sku') or ''}): no unit cost set")
            continue
        cost_currency = unit_cost.get("currencyCode")
        if order_currency and cost_currency and cost_currency != order_currency:
            logger.warning(
                f"Order {order_name}: unit cost currency {cost_currency} differs from "
                f"order currency {order_currency} for {item.get('title', 'Unknown')}"
            )
        line_cost = float(unit_cost["amount"]) * quantity
        product_cost += line_cost
        debug_log(logger, f"  - {item.get('title', 'Unknown')} (SKU: {variant.get('sku') or ''}): {quantity} x {unit_cost['amount']} = {line_cost}")

    profit = revenue - product_cost
    margin_percent = round(profit / revenue * 100, 2) if revenue else None
    result = {
        "revenue": round(revenue, 2),
        "product_cost": round(product_cost, 2),
        "profit": round(profit, 2),
        "margin_percent": margin_percent,
        "missing_cost_count": missing_cost_count,
        "truncated": False,
    }
    debug_log(logger, f"Order {order_name}: profit {result}")
    return result


class RuleEngine:
    """Engine for evaluating and applying order processing rules"""
    
    def __init__(self, db_session: Session = None):
        self.db_session = db_session
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
            "is_not_empty": self._is_not_empty,
            # Fraud-specific operators
            "risk_level_equals": self._risk_level_equals,
            "delivery_status_contains": self._delivery_status_contains,
            "fraud_boolean_equals": self._fraud_boolean_equals,
            "fraud_ratio_greater_than": self._fraud_ratio_greater_than,
            "fraud_ratio_less_than": self._fraud_ratio_less_than,
            "multiple_greater_than": self._multiple_greater_than
        }
    
    def evaluate_rule(self, rule: ProcessingRule, order: Dict[str, Any], excluded_skus: List[str] = None, store_context: Any = None) -> bool:
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
                result = self._evaluate_condition(condition, order, excluded_skus, store_context)
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
    
    def _evaluate_condition(self, condition: Dict[str, Any], order: Dict[str, Any], excluded_skus: List[str] = None, store_context: Any = None) -> bool:
        """Evaluate a single condition"""
        try:
            field = condition.get("field")
            operator = condition.get("operator")
            expected_value = condition.get("value")
            
            if not field or not operator:
                logger.error(f"Invalid condition: missing field or operator")
                return False
            
            # Get the actual value from the order
            actual_value = self._get_order_field_value(field, order, excluded_skus, store_context)
            
            if field == "duplicate_within_7days":
                debug_log(logger, f"CONDITION EVALUATION DEBUG - duplicate_within_7days:")
                debug_log(logger, f"  - Field: {field}")
                debug_log(logger, f"  - Operator: {operator}")
                debug_log(logger, f"  - Expected value: {expected_value} (type: {type(expected_value)})")
                debug_log(logger, f"  - Actual value: {actual_value} (type: {type(actual_value)})")

                # Fix boolean comparison for duplicate field
                if isinstance(expected_value, str) and expected_value.lower() in ('true', 'false'):
                    expected_value = expected_value.lower() == 'true'
                    debug_log(logger, f"  - Converted expected to boolean: {expected_value}")
            
            # Convert expected value to uppercase for province/state/country fields to make comparison case-insensitive
            if field in ["shipping_province", "shipping_country", "billing_province", "billing_country", "shipping_state"]:
                if isinstance(expected_value, str):
                    expected_value = expected_value.upper()
                elif isinstance(expected_value, list):
                    # Convert all list items to uppercase for case-insensitive comparison
                    expected_value = [str(item).upper() for item in expected_value]
            
            # Special handling for fulfillment_location field with equals/not_equals
            # For fulfillment_location, check if ANY location in the list matches (not exact list equality)
            if field == "fulfillment_location" and operator in ["equals", "not_equals"]:
                if isinstance(actual_value, list):
                    is_match = expected_value in actual_value
                    return is_match if operator == "equals" else not is_match
                else:
                    # Fallback to normal comparison if not a list
                    is_match = actual_value == expected_value
                    return is_match if operator == "equals" else not is_match
            
            # Apply the operator normally for all other cases
            if operator not in self.operators:
                logger.error(f"Unknown operator: {operator}")
                return False
            
            return self.operators[operator](actual_value, expected_value)
            
        except Exception as e:
            logger.error(f"Error evaluating condition: {str(e)}")
            return False
    
    def _get_order_field_value(self, field: str, order: Dict[str, Any], excluded_skus: List[str] = None, store_context: Any = None) -> Any:
        """Extract field value from order data"""
        try:
            # Check if this is a fraud analysis field
            fraud_fields = [
                "first_time_customer", "transaction_attempts", "customer_name", "duplicate_within_7days",
                "previous_order_delivery_status", "previous_order_total", "current_order_total",
                "fraud_risk_level", "customer_notes", "billing_outside_us",
                "same_billing_shipping", "shipping_state", "current_delivery_status",
                "delivery_success_rate", "average_delivery_days", "total_orders", "delivered_orders",
                "failed_deliveries", "fraud_analysis_id", "analysis_timestamp", "fraud_order_total_multiple",
                "order_total", "order_name", "days_since_last_delivery", "customer_total_orders",
                "previous_order_cancelled"  # Added new field for previous order cancellation status
            ]
            
            # Fraud rule evaluation passes a flat fraud-analysis dict that carries these
            # keys explicitly; a raw Shopify order never does, so fall through to the
            # order extractors below for names shared with them (e.g. order_total).
            if field in fraud_fields and field in order:
                value = order.get(field)

                if field == "duplicate_within_7days":
                    debug_log(logger, f"RULE ENGINE DEBUG - Accessing duplicate_within_7days:")
                    debug_log(logger, f"  - Raw value from order data: {value}")
                    debug_log(logger, f"  - Type: {type(value)}")
                    debug_log(logger, f"  - Order name: {order.get('order_name', 'Unknown')}")

                if field == "shipping_state":
                    debug_log(logger, f"RULE ENGINE DEBUG - Accessing shipping_state:")
                    debug_log(logger, f"  - Raw value from order data: {value}")
                    debug_log(logger, f"  - Type: {type(value)}")
                    debug_log(logger, f"  - Order name: {order.get('order_name', 'Unknown')}")

                if field == "fraud_order_total_multiple":
                    debug_log(logger, f"Retrieved fraud_order_total_multiple: {value}")

                if field == "days_since_last_delivery":
                    debug_log(logger, f"Retrieved days_since_last_delivery: {value}")
                
                return value
            
            # Handle nested field access with dot notation for regular order fields
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
            # NOTE: .get(key, {}) does not protect against JSON null values —
            # Shopify returns shippingAddress: null (digital orders),
            # customer: null (guest checkout), variant: null (deleted products) —
            # so every nested access below uses `or {}` / `or ""`.
            if field == "order_total":
                total_price = (order.get("totalPriceSet") or {}).get("shopMoney") or {}
                return float(total_price.get("amount") or 0)
            
            elif field == "order_weight":
                # Shopify returns weight in grams via currentTotalWeight field
                weight_grams = order.get("currentTotalWeight", 0)
                if weight_grams is None or weight_grams == "":
                    debug_log(logger, f"Order {order.get('name', 'unknown')}: No weight data available")
                    return 0
                weight_grams = float(weight_grams)

                # Calculate weight from individual line items, excluding specified SKUs
                line_items_conn = order.get("lineItems") or {}
                line_items = line_items_conn.get("edges", [])
                # Sync queries fetch a bounded number of line items; when the
                # connection has more pages the calculated sum is a partial total
                line_items_truncated = bool((line_items_conn.get("pageInfo") or {}).get("hasNextPage"))
                total_calculated_weight = 0
                excluded_skus = excluded_skus or []
                excluded_count = 0

                debug_log(logger, f"Order {order.get('name', 'unknown')}: Calculating weight (excluding {len(excluded_skus)} SKU patterns)")
                
                for item_edge in line_items:
                    item = item_edge["node"]
                    variant = item.get("variant") or {}
                    sku = variant.get("sku") or ""
                    
                    # Check if this SKU should be excluded
                    skip_item = False
                    if sku and excluded_skus:
                        for excluded_pattern in excluded_skus:
                            if excluded_pattern.lower() in sku.lower():
                                skip_item = True
                                excluded_count += 1
                                debug_log(logger, f"  - EXCLUDED: {item.get('title', 'Unknown')} (SKU: {sku}) matches pattern '{excluded_pattern}'")
                                break
                    
                    if skip_item:
                        continue
                    
                    quantity = item.get("quantity") or 0
                    inventory_item = variant.get("inventoryItem") or {}
                    measurement = inventory_item.get("measurement") or {}
                    weight_obj = measurement.get("weight") or {}

                    item_weight_value = weight_obj.get("value") or 0
                    item_weight_unit = weight_obj.get("unit") or "GRAMS"
                    
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

                    debug_log(logger, f"  - {item.get('title', 'Unknown')} (SKU: {sku}): {quantity} x {item_weight_value} {item_weight_unit} = {total_item_weight}g")

                if excluded_count > 0:
                    debug_log(logger, f"Order {order.get('name', 'unknown')}: Excluded {excluded_count} items from weight calculation")

                debug_log(logger, f"Order {order.get('name', 'unknown')}: Shopify currentTotalWeight = {weight_grams}g")
                debug_log(logger, f"Order {order.get('name', 'unknown')}: Calculated from included line items = {total_calculated_weight}g")
                
                # When SKUs are excluded, always use calculated weight instead of Shopify's total
                if excluded_skus and excluded_count > 0:
                    if line_items_truncated:
                        logger.warning(
                            f"Order {order.get('name', 'unknown')}: line items truncated by page size — "
                            f"SKU-excluded weight ({total_calculated_weight}g) may undercount"
                        )
                    debug_log(logger, f"Order {order.get('name', 'unknown')}: Using calculated weight due to SKU exclusions")
                    return total_calculated_weight

                # A truncated line-item list means the calculated sum is partial —
                # Shopify's own total is authoritative in that case
                if line_items_truncated:
                    debug_log(logger, f"Order {order.get('name', 'unknown')}: line items truncated, using Shopify currentTotalWeight")
                    return weight_grams

                # Use calculated weight if it's significantly different from Shopify's value
                # This handles cases where Shopify's currentTotalWeight is incorrect
                if abs(total_calculated_weight - weight_grams) > 1:  # More than 1g difference
                    logger.warning(f"Order {order.get('name', 'unknown')}: Large discrepancy between Shopify currentTotalWeight ({weight_grams}g) and calculated weight ({total_calculated_weight}g). Using calculated weight.")
                    return total_calculated_weight

                return weight_grams
            
            elif field == "shipping_province":
                shipping_addr = order.get("shippingAddress") or {}
                province = (shipping_addr.get("province") or "").strip()
                debug_log(logger, f"Order {order.get('name', 'unknown')}: Raw shipping province = '{province}', Uppercase = '{province.upper()}'")
                return province.upper()

            elif field == "shipping_country":
                shipping_addr = order.get("shippingAddress") or {}
                return (shipping_addr.get("country") or "").strip().upper()

            elif field == "shipping_city":
                shipping_addr = order.get("shippingAddress") or {}
                return (shipping_addr.get("city") or "").strip()

            elif field == "shipping_method":
                shipping_lines = (order.get("shippingLines") or {}).get("edges", [])
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
            
            elif field == "fulfillment_location":
                locations = []
                fulfillment_orders = order.get("fulfillmentOrders", {}).get("edges", [])
                
                for fo_edge in fulfillment_orders:
                    fo = fo_edge["node"]
                    assigned_location = fo.get("assignedLocation", {}).get("location", {})
                    
                    if assigned_location:
                        location_id = assigned_location.get("id", "")
                        location_name = assigned_location.get("name", "")
                        
                        # Add both location ID and name to support different matching styles
                        if location_id:
                            locations.append(location_id)
                        if location_name:
                            locations.append(location_name)
                
                # If we have store context, try to resolve any location aliases
                # that might map to these actual locations
                if store_context and hasattr(store_context, 'id'):
                    try:
                        logger.info(f"Starting alias resolution for store {store_context.id}")
                        from database import get_db_session
                        from models import LocationAlias, LocationMapping

                        location_ids = [loc for loc in locations if loc.startswith("gid://")]
                        logger.info(f"Location IDs to resolve: {location_ids}")

                        if location_ids:
                            with get_db_session() as db:
                                aliases = db.query(LocationAlias).join(LocationMapping).filter(
                                    LocationMapping.store_id == store_context.id,
                                    LocationMapping.shopify_location_id.in_(location_ids),
                                    LocationMapping.is_active == True,
                                    LocationAlias.is_active == True
                                ).all()

                                logger.info(f"Found {len(aliases)} aliases: {[a.alias_name for a in aliases]}")

                                for alias in aliases:
                                    if alias.alias_name not in locations:
                                        locations.append(alias.alias_name)
                                        logger.info(f"Added alias: {alias.alias_name}")
                        else:
                            logger.info("No location IDs found to resolve aliases for")

                    except Exception as e:
                        logger.warning(f"Could not resolve location aliases: {e}", exc_info=True)
                else:
                    logger.info(f"No store context for alias resolution (context: {store_context})")
                
                # Remove duplicates while preserving order
                unique_locations = []
                for loc in locations:
                    if loc not in unique_locations:
                        unique_locations.append(loc)
                
                logger.info(f"Order {order.get('name', 'unknown')}: Fulfillment locations = {unique_locations}")
                return unique_locations
            
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

            elif field in PROFIT_FIELDS:
                profit_data = calculate_order_profit(order)
                if field == "order_profit":
                    return profit_data["profit"]
                if field == "order_profit_margin":
                    return profit_data["margin_percent"]
                return profit_data["missing_cost_count"]

            # Fraud-specific field extractors
            elif field.startswith("fraud_"):
                return self._get_fraud_field_value(field, order, store_context)
            
            return value
            
        except Exception as e:
            logger.error(f"Error getting field {field}: {str(e)}")
            return None
    
    # Operator implementations
    def _equals(self, actual: Any, expected: Any) -> bool:
        # Special handling for boolean comparisons with string values
        if isinstance(actual, bool) and isinstance(expected, str):
            # Convert string boolean to actual boolean for comparison
            if expected.lower() in ('true', '1', 'yes'):
                expected = True
            elif expected.lower() in ('false', '0', 'no'):
                expected = False
        elif isinstance(actual, str) and isinstance(expected, bool):
            # Convert string boolean to actual boolean for comparison
            if actual.lower() in ('true', '1', 'yes'):
                actual = True
            elif actual.lower() in ('false', '0', 'no'):
                actual = False
        
        result = actual == expected
        logger.info(f"Equals comparison: {actual} (type: {type(actual).__name__}) == {expected} (type: {type(expected).__name__}) = {result}")
        return result
    
    def _not_equals(self, actual: Any, expected: Any) -> bool:
        # Use the same boolean conversion logic as _equals
        if isinstance(actual, bool) and isinstance(expected, str):
            if expected.lower() in ('true', '1', 'yes'):
                expected = True
            elif expected.lower() in ('false', '0', 'no'):
                expected = False
        elif isinstance(actual, str) and isinstance(expected, bool):
            if actual.lower() in ('true', '1', 'yes'):
                actual = True
            elif actual.lower() in ('false', '0', 'no'):
                actual = False
        
        return actual != expected
    
    def _greater_than(self, actual: Any, expected: Any) -> bool:
        try:
            actual_value = float(actual)
            expected_value = float(expected)
            result = actual_value > expected_value
            logger.info(f"Greater than comparison: {actual_value} > {expected_value} = {result}")
            return result
        except (TypeError, ValueError) as e:
            logger.warning(f"Greater than comparison failed: actual={actual}, expected={expected}, error={e}")
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
        return safe_regex_match(expected, str(actual))
    
    def _is_empty(self, actual: Any, expected: Any) -> bool:
        if actual is None:
            return True
        if isinstance(actual, (list, dict, str)):
            return len(actual) == 0
        return False
    
    def _is_not_empty(self, actual: Any, expected: Any) -> bool:
        return not self._is_empty(actual, expected)

    # Fraud-specific operators
    def _risk_level_equals(self, actual: Any, expected: str) -> bool:
        """Compare fraud risk levels (case-insensitive)"""
        if actual is None:
            return False
        return str(actual).upper() == str(expected).upper()
    
    def _delivery_status_contains(self, actual: Any, expected: str) -> bool:
        """Check if delivery status contains a specific string (case-insensitive)"""
        if actual is None:
            return False
        return str(expected).lower() in str(actual).lower()
    
    def _fraud_boolean_equals(self, actual: Any, expected: Any) -> bool:
        """Compare boolean values with null safety"""
        if actual is None:
            return expected is None or expected == False
        return bool(actual) == bool(expected)
    
    def _fraud_ratio_greater_than(self, actual: Any, expected: Any) -> bool:
        """Compare ratios with null safety and decimal precision"""
        try:
            if actual is None:
                return False
            actual_decimal = Decimal(str(actual))
            expected_decimal = Decimal(str(expected))
            return actual_decimal > expected_decimal
        except (TypeError, ValueError):
            return False
    
    def _fraud_ratio_less_than(self, actual: Any, expected: Any) -> bool:
        """Compare ratios with null safety and decimal precision"""
        try:
            if actual is None:
                return False
            actual_decimal = Decimal(str(actual))
            expected_decimal = Decimal(str(expected))
            return actual_decimal < expected_decimal
        except (TypeError, ValueError):
            return False

    def _multiple_greater_than(self, actual: Any, expected: Any) -> bool:
        """Compare order total multiple with null safety - returns False if no previous order"""
        try:
            if actual is None:
                # No previous order or unable to calculate multiple - return False (ignore condition)
                return False
            actual_decimal = Decimal(str(actual))
            expected_decimal = Decimal(str(expected))
            return actual_decimal > expected_decimal
        except (TypeError, ValueError):
            return False

    def _get_fraud_field_value(self, field: str, order: Dict[str, Any], store_context: Any = None) -> Any:
        """Extract fraud analysis field values with null-safe fallbacks"""
        try:
            if not self.db_session:
                logger.warning("No database session available for fraud field extraction")
                return None
            
            # Get order information
            order_info = order.get('order_info', {})
            order_name = order_info.get('name', '') or order.get('name', '')
            
            if not order_name:
                logger.warning("No order name found for fraud analysis lookup")
                return None
            
            # Look up fraud analysis record
            fraud_analysis = None
            try:
                fraud_analysis = self.db_session.query(FraudAnalysis).filter(
                    FraudAnalysis.order_name == order_name
                ).first()
                
                if not fraud_analysis:
                    logger.warning(f"No fraud analysis found for order {order_name}")
                    return self._get_fraud_field_fallback(field, order)
                    
            except Exception as e:
                logger.error(f"Error querying fraud analysis for order {order_name}: {str(e)}")
                return self._get_fraud_field_fallback(field, order)
            
            # Extract specific fraud fields with null-safe handling
            try:
                if field == "fraud_is_first_time_customer":
                    return fraud_analysis.is_first_time_customer if fraud_analysis.is_first_time_customer is not None else True
                
                elif field == "fraud_duplicate_within_7days":
                    return fraud_analysis.duplicate_within_7days if fraud_analysis.duplicate_within_7days is not None else False
                
                elif field == "fraud_billing_address_outside_us":
                    return fraud_analysis.billing_address_outside_us if fraud_analysis.billing_address_outside_us is not None else False
                
                elif field == "fraud_shopify_fraud_risk_level":
                    return fraud_analysis.shopify_fraud_risk_level or "UNKNOWN"
                
                elif field == "fraud_transaction_attempts_count":
                    return fraud_analysis.transaction_attempts_count if fraud_analysis.transaction_attempts_count is not None else 0
                
                elif field == "fraud_age_checker_detected":
                    return fraud_analysis.age_checker_detected if fraud_analysis.age_checker_detected is not None else False
                
                elif field == "fraud_same_billing_shipping":
                    return fraud_analysis.same_billing_shipping if fraud_analysis.same_billing_shipping is not None else True
                
                elif field == "fraud_shipping_state":
                    return fraud_analysis.shipping_state or None
                
                elif field == "fraud_previous_order_delivery_status":
                    return fraud_analysis.previous_order_delivery_status or "Unknown"
                
                elif field == "fraud_current_order_total":
                    if fraud_analysis.current_order_total is not None:
                        return float(fraud_analysis.current_order_total)
                    return 0.0
                
                elif field == "fraud_previous_order_total":
                    if fraud_analysis.previous_order_total is not None:
                        return float(fraud_analysis.previous_order_total)
                    return 0.0
                
                elif field == "fraud_order_total_ratio":
                    # Calculate ratio of current to previous order total
                    current = fraud_analysis.current_order_total
                    previous = fraud_analysis.previous_order_total
                    
                    if current is None or previous is None or previous == 0:
                        return 1.0  # Default ratio when no comparison possible
                    
                    try:
                        return float(current) / float(previous)
                    except (TypeError, ValueError, ZeroDivisionError):
                        return 1.0

                elif field == "fraud_order_total_multiple":
                    # Calculate multiple of current order total vs previous order total
                    current = fraud_analysis.current_order_total
                    previous = fraud_analysis.previous_order_total
                    
                    # Return None if no previous order or previous order is 0/None
                    # This will cause the condition to be ignored (return False)
                    if previous is None or previous == 0 or current is None:
                        logger.info(f"Order total multiple: No valid previous order total (current: {current}, previous: {previous})")
                        return None
                    
                    try:
                        multiple = float(current) / float(previous)
                        logger.info(f"Order total multiple: {current} / {previous} = {multiple}")
                        return multiple
                    except (TypeError, ValueError, ZeroDivisionError):
                        logger.warning(f"Error calculating order total multiple (current: {current}, previous: {previous})")
                        return None
                
                else:
                    logger.warning(f"Unknown fraud field: {field}")
                    return None
                    
            except Exception as e:
                logger.error(f"Error extracting fraud field {field}: {str(e)}")
                return self._get_fraud_field_fallback(field, order)
            
        except Exception as e:
            logger.error(f"Error in fraud field extraction for {field}: {str(e)}")
            return self._get_fraud_field_fallback(field, order)
    
    def _get_fraud_field_fallback(self, field: str, order: Dict[str, Any]) -> Any:
        """Provide fallback values for fraud fields when fraud analysis is not available"""
        try:
            # Return safe default values that won't break rule evaluation
            fallback_values = {
                "fraud_is_first_time_customer": True,  # Conservative default
                "fraud_duplicate_within_7days": False,
                "fraud_billing_address_outside_us": False,
                "fraud_shopify_fraud_risk_level": "UNKNOWN",
                "fraud_transaction_attempts_count": 1,  # Assume at least one attempt
                "fraud_age_checker_detected": False,
                "fraud_same_billing_shipping": True,  # Conservative default
                "fraud_shipping_state": None,
                "fraud_previous_order_delivery_status": "Unknown",
                "fraud_current_order_total": 0.0,
                "fraud_previous_order_total": 0.0,
                "fraud_order_total_ratio": 1.0,
                "fraud_order_total_multiple": None  # No previous order data available
            }
            
            fallback = fallback_values.get(field)
            logger.info(f"Using fallback value for {field}: {fallback}")
            return fallback
            
        except Exception as e:
            logger.error(f"Error in fraud field fallback for {field}: {str(e)}")
            return None

    def process_fraud_actions(self, actions: List[Dict[str, Any]], order: Dict[str, Any], store_context: Any = None) -> List[Dict[str, Any]]:
        """Process fraud-specific actions and return action results"""
        try:
            results = []
            
            for action in actions:
                action_type = action.get("type")
                action_value = action.get("value", "")
                
                try:
                    if action_type == "flag_high_risk":
                        # Add high-risk fraud tag
                        tag_result = {
                            "type": "add_tag",
                            "value": action_value or "HIGH_FRAUD_RISK",
                            "status": "success",
                            "message": f"Added fraud flag tag: {action_value or 'HIGH_FRAUD_RISK'}"
                        }
                        results.append(tag_result)
                    
                    elif action_type == "add_custom_tag":
                        # Add custom fraud-related tag
                        if action_value:
                            tag_result = {
                                "type": "add_tag", 
                                "value": action_value,
                                "status": "success",
                                "message": f"Added custom fraud tag: {action_value}"
                            }
                            results.append(tag_result)
                        else:
                            results.append({
                                "type": "add_custom_tag",
                                "status": "error", 
                                "message": "Custom tag value cannot be empty"
                            })
                    
                    else:
                        # Pass through non-fraud actions unchanged
                        results.append({
                            "type": action_type,
                            "value": action_value,
                            "status": "passthrough",
                            "message": f"Non-fraud action: {action_type}"
                        })
                        
                except Exception as e:
                    logger.error(f"Error processing fraud action {action_type}: {str(e)}")
                    results.append({
                        "type": action_type,
                        "status": "error",
                        "message": f"Error processing action: {str(e)}"
                    })
            
            return results
            
        except Exception as e:
            logger.error(f"Error processing fraud actions: {str(e)}")
            return []

    def get_available_fields(self) -> List[Dict[str, str]]:
        """Get list of available order fields for rule creation"""
        return [
            # Standard order fields
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
            {"field": "fulfillment_location", "label": "Fulfillment Location", "type": "array"},
            {"field": "order_created_at", "label": "Order Created Date", "type": "datetime"},
            {"field": "line_item_count", "label": "Number of Line Items", "type": "number"},
            {"field": "total_quantity", "label": "Total Quantity", "type": "number"},
            {"field": "order_profit", "label": "Order Profit (revenue − product cost, excl. tax)", "type": "number"},
            {"field": "order_profit_margin", "label": "Order Profit Margin (%)", "type": "number"},
            {"field": "line_items_missing_cost", "label": "Line Items Missing Cost", "type": "number"},

            # Fraud analysis fields
            {"field": "fraud_is_first_time_customer", "label": "Fraud: Is First Time Customer", "type": "boolean"},
            {"field": "fraud_duplicate_within_7days", "label": "Fraud: Duplicate Within 7 Days", "type": "boolean"},
            {"field": "fraud_billing_address_outside_us", "label": "Fraud: Billing Address Outside US", "type": "boolean"},
            {"field": "fraud_shopify_fraud_risk_level", "label": "Fraud: Shopify Risk Level", "type": "string"},
            {"field": "fraud_transaction_attempts_count", "label": "Fraud: Transaction Attempts Count", "type": "number"},
            {"field": "fraud_age_checker_detected", "label": "Fraud: Age Checker Detected", "type": "boolean"},
            {"field": "fraud_same_billing_shipping", "label": "Fraud: Same Billing/Shipping Address", "type": "boolean"},
            {"field": "fraud_shipping_state", "label": "Fraud: Shipping State", "type": "string"},
            {"field": "fraud_previous_order_delivery_status", "label": "Fraud: Previous Order Delivery Status", "type": "string"},
            {"field": "fraud_current_order_total", "label": "Fraud: Current Order Total", "type": "number"},
            {"field": "fraud_previous_order_total", "label": "Fraud: Previous Order Total", "type": "number"},
            {"field": "fraud_order_total_ratio", "label": "Fraud: Order Total Ratio (Current/Previous)", "type": "number"},
            {"field": "fraud_order_total_multiple", "label": "Order Total Multiple (vs Previous Order)", "type": "number"},
            {"field": "customer_total_orders", "label": "Customer Total Orders", "type": "number"},
        ]
    
    def get_available_operators(self) -> List[Dict[str, str]]:
        """Get list of available operators"""
        return [
            # Standard operators
            {"operator": "equals", "label": "Equals", "types": ["string", "number", "boolean"]},
            {"operator": "not_equals", "label": "Not Equals", "types": ["string", "number", "boolean"]},
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
            
            # Fraud-specific operators
            {"operator": "risk_level_equals", "label": "Risk Level Equals", "types": ["fraud_risk"]},
            {"operator": "delivery_status_contains", "label": "Delivery Status Contains", "types": ["fraud_delivery"]},
            {"operator": "fraud_ratio_greater_than", "label": "Fraud Ratio Greater Than", "types": ["fraud_ratio"]},
            {"operator": "fraud_ratio_less_than", "label": "Fraud Ratio Less Than", "types": ["fraud_ratio"]},
            {"operator": "multiple_greater_than", "label": "Multiple Greater Than", "types": ["number"]},
        ]