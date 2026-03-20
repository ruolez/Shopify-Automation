"""
Fraud Rule Processor service for evaluating and applying fraud detection rules.
Integrates with the existing order processing pipeline to run fraud analysis rules.
"""
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from models import FraudDetectionRule, FraudAnalysis, OrderLog, User, ShopifyStore
from rule_engine import RuleEngine
from fraud_service import FraudAnalysisService
from logging_config import get_logger, debug_log, DEBUG_LOGGING

logger = get_logger(__name__)


class FraudRuleProcessor:
    """Service for processing fraud detection rules against order fraud analysis data."""
    
    def __init__(self, db_session: Session, user: User, store: ShopifyStore, shopify_client):
        """Initialize the fraud rule processor.
        
        Args:
            db_session: Database session
            user: User instance
            store: ShopifyStore instance
            shopify_client: ShopifyClient instance for API calls
        """
        self.db = db_session
        self.user = user
        self.store = store
        self.shopify_client = shopify_client
        self.rule_engine = RuleEngine(db_session)
        
    async def process_fraud_rules_for_order(self, order_data: Dict[str, Any], fraud_analysis: FraudAnalysis) -> Dict[str, Any]:
        """Process all active fraud rules against an order's fraud analysis.
        
        Args:
            order_data: Raw order data from Shopify
            fraud_analysis: FraudAnalysis record for the order
            
        Returns:
            Dictionary with processing results and actions taken
        """
        try:
            # Extract order name - handle both direct GraphQL and nested order_info formats
            if 'order_info' in order_data:
                order_name = order_data.get('order_info', {}).get('name', 'Unknown')
            else:
                order_name = order_data.get('name', 'Unknown')
            logger.info(f"Starting fraud rule processing for order {order_name}")
            
            # CRITICAL: Ensure fresh database session and data
            self.db.expire_all()  # Clear session cache
            self.db.commit()      # Commit any pending changes
            
            # Re-fetch fraud analysis to ensure we have latest data
            fresh_fraud_analysis = self.db.query(FraudAnalysis).filter(
                FraudAnalysis.id == fraud_analysis.id
            ).first()
            
            if not fresh_fraud_analysis:
                logger.error(f"Failed to re-fetch fraud analysis {fraud_analysis.id}")
                return {
                    "rules_processed": 0,
                    "rules_matched": 0,
                    "actions_executed": 0,
                    "results": [],
                    "error": "Failed to fetch fresh fraud analysis data"
                }
            
            fraud_analysis = fresh_fraud_analysis
            debug_log(logger, f"REFRESHED fraud analysis {fraud_analysis.id} with fresh database query")
            debug_log(logger, f"  - Analysis timestamp: {fraud_analysis.analysis_timestamp}")
            debug_log(logger, f"  - duplicate_within_7days (DB): {fraud_analysis.duplicate_within_7days}")
            debug_log(logger, f"  - customer_name (DB): {fraud_analysis.customer_name}")
            debug_log(logger, f"  - first_time_customer (DB): {fraud_analysis.is_first_time_customer}")
            
            # Get all active fraud rules for the user, ordered by priority
            fraud_rules = self.db.query(FraudDetectionRule).filter(
                FraudDetectionRule.user_id == self.user.id,
                FraudDetectionRule.is_active == True
            ).order_by(FraudDetectionRule.priority.asc()).all()
            
            if not fraud_rules:
                logger.info(f"No active fraud rules found for user {self.user.id}")
                return {
                    "rules_processed": 0,
                    "rules_matched": 0,
                    "actions_executed": 0,
                    "results": []
                }
            
            logger.info(f"Processing {len(fraud_rules)} fraud detection rules for order {order_name}")
            
            # Convert fraud analysis to rule evaluation format
            fraud_data = self._convert_fraud_analysis_to_rule_data(fraud_analysis)
            
            debug_log(logger, f"FRAUD DATA CONVERSION DEBUG for order {order_name}:")
            debug_log(logger, f"  - fraud_analysis_id: {fraud_data.get('fraud_analysis_id')}")
            debug_log(logger, f"  - duplicate_within_7days: {fraud_data.get('duplicate_within_7days')} (type: {type(fraud_data.get('duplicate_within_7days'))})")
            debug_log(logger, f"  - customer_name: {fraud_data.get('customer_name')}")
            debug_log(logger, f"  - first_time_customer: {fraud_data.get('first_time_customer')}")
            
            results = {
                "rules_processed": 0,
                "rules_matched": 0,
                "actions_executed": 0,
                "results": []
            }
            
            # Process each rule
            for rule in fraud_rules:
                try:
                    rule_result = await self._process_single_fraud_rule(rule, fraud_data, order_name)
                    results["results"].append(rule_result)
                    results["rules_processed"] += 1
                    
                    if rule_result["matched"]:
                        results["rules_matched"] += 1
                        results["actions_executed"] += rule_result["actions_executed"]
                        
                        # Add delay if specified
                        if rule.delay_ms > 0:
                            logger.info(f"Applying {rule.delay_ms}ms delay after fraud rule '{rule.name}'")
                            await asyncio.sleep(rule.delay_ms / 1000.0)
                            
                except Exception as e:
                    logger.error(f"Error processing fraud rule '{rule.name}': {str(e)}", exc_info=True)
                    results["results"].append({
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "matched": False,
                        "actions_executed": 0,
                        "error": str(e)
                    })
                    results["rules_processed"] += 1
            
            logger.info(f"Fraud rule processing completed for order {order_name}: "
                       f"{results['rules_matched']}/{results['rules_processed']} rules matched, "
                       f"{results['actions_executed']} actions executed")
            
            # Update the FraudAnalysis record with rule results
            # CRITICAL: Ensure we're updating the fresh instance
            self._update_fraud_analysis_with_results(fraud_analysis, results)
            
            return results
            
        except Exception as e:
            logger.error(f"Error in fraud rule processing: {str(e)}", exc_info=True)
            return {
                "rules_processed": 0,
                "rules_matched": 0,
                "actions_executed": 0,
                "results": [],
                "error": str(e)
            }
    
    async def _process_single_fraud_rule(self, rule: FraudDetectionRule, fraud_data: Dict[str, Any], order_name: str) -> Dict[str, Any]:
        """Process a single fraud detection rule.
        
        Args:
            rule: FraudDetectionRule to evaluate
            fraud_data: Fraud analysis data formatted for rule evaluation
            order_name: Order name for logging
            
        Returns:
            Dictionary with rule processing results
        """
        result = {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "matched": False,
            "actions_executed": 0,
            "actions": []
        }
        
        try:
            debug_log(logger, f"EVALUATING FRAUD RULE '{rule.name}' (ID: {rule.id}) for order {order_name}")
            debug_log(logger, f"  - Rule conditions: {rule.conditions}")

            # Log specific values being checked if duplicate detection is in conditions
            if rule.conditions:
                conditions_str = str(rule.conditions)
                if 'duplicate_within_7days' in conditions_str:
                    debug_log(logger, f"  Rule checks duplicate_within_7days")
                    debug_log(logger, f"  - Current value in fraud_data: {fraud_data.get('duplicate_within_7days')}")
                if 'customer_name' in conditions_str:
                    debug_log(logger, f"  Rule checks customer_name")
                    debug_log(logger, f"  - Current value in fraud_data: {fraud_data.get('customer_name')}")
                if 'first_time_customer' in conditions_str:
                    debug_log(logger, f"  Rule checks first_time_customer")
                    debug_log(logger, f"  - Current value in fraud_data: {fraud_data.get('first_time_customer')}")
                if 'customer_total_orders' in conditions_str:
                    debug_log(logger, f"  Rule checks customer_total_orders")
                    debug_log(logger, f"  - Current value in fraud_data: {fraud_data.get('customer_total_orders')}")

            # Evaluate the fraud rule against fraud analysis data
            matched = self.rule_engine.evaluate_rule(rule, fraud_data)
            result["matched"] = matched

            debug_log(logger, f"  - Rule evaluation result: {'MATCHED' if matched else 'NOT MATCHED'}")
            
            if matched:
                logger.info(f"Fraud rule '{rule.name}' matched for order {order_name}")
                
                # Execute rule actions
                for action in rule.actions:
                    try:
                        action_result = await self._execute_fraud_action(action, fraud_data, order_name, rule.name)
                        result["actions"].append(action_result)
                        if action_result.get("success", False):
                            result["actions_executed"] += 1
                    except Exception as e:
                        logger.error(f"Error executing fraud action {action.get('type', 'unknown')}: {str(e)}")
                        result["actions"].append({
                            "type": action.get("type", "unknown"),
                            "success": False,
                            "error": str(e)
                        })
            else:
                logger.debug(f"Fraud rule '{rule.name}' did not match for order {order_name}")
                
        except Exception as e:
            logger.error(f"Error evaluating fraud rule '{rule.name}': {str(e)}")
            result["error"] = str(e)
            
        return result
    
    def _convert_fraud_analysis_to_rule_data(self, fraud_analysis: FraudAnalysis) -> Dict[str, Any]:
        """Convert FraudAnalysis record to format suitable for rule evaluation.
        
        Args:
            fraud_analysis: FraudAnalysis database record
            
        Returns:
            Dictionary formatted for rule engine evaluation
        """
        try:
            debug_log(logger, f"CONVERTING FRAUD ANALYSIS {fraud_analysis.id} TO RULE DATA:")
            debug_log(logger, f"  - Order: {fraud_analysis.order_name}")
            debug_log(logger, f"  - Analysis timestamp: {fraud_analysis.analysis_timestamp}")
            debug_log(logger, f"  - duplicate_within_7days (SOURCE): {fraud_analysis.duplicate_within_7days}")
            debug_log(logger, f"  - customer_name (SOURCE): {fraud_analysis.customer_name}")
            debug_log(logger, f"  - is_first_time_customer (SOURCE): {fraud_analysis.is_first_time_customer}")
            debug_log(logger, f"  - customer_total_orders (SOURCE): {fraud_analysis.customer_total_orders}")
            debug_log(logger, f"  - shopify_fraud_risk_level (SOURCE): {fraud_analysis.shopify_fraud_risk_level}")
            
            # Extract delivery analytics if available
            delivery_analytics = fraud_analysis.delivery_analytics or {}
            delivery_history = delivery_analytics.get('customer_delivery_history', {})
            
            # Calculate order total multiple if both values are available
            fraud_order_total_multiple = None
            if (fraud_analysis.current_order_total and fraud_analysis.previous_order_total 
                and fraud_analysis.previous_order_total > 0):
                fraud_order_total_multiple = float(fraud_analysis.current_order_total) / float(fraud_analysis.previous_order_total)
            
            # Convert to rule evaluation format
            fraud_data = {
                "fraud_analysis_id": fraud_analysis.id,
                "order_name": fraud_analysis.order_name,
                "order_id": fraud_analysis.shopify_order_id,
                "first_time_customer": fraud_analysis.is_first_time_customer,
                "order_total": float(fraud_analysis.order_total) if fraud_analysis.order_total else 0.0,
                "transaction_attempts": fraud_analysis.transaction_attempts_count or 0,
                "customer_name": fraud_analysis.customer_name,
                "duplicate_within_7days": fraud_analysis.duplicate_within_7days,
                "previous_order_delivery_status": fraud_analysis.previous_order_delivery_status,
                "previous_order_total": float(fraud_analysis.previous_order_total) if fraud_analysis.previous_order_total else None,
                "current_order_total": float(fraud_analysis.current_order_total) if fraud_analysis.current_order_total else 0.0,
                "fraud_risk_level": fraud_analysis.shopify_fraud_risk_level,
                "fraud_order_total_multiple": fraud_order_total_multiple,
                "customer_notes": fraud_analysis.customer_notes,
                "billing_outside_us": fraud_analysis.billing_address_outside_us,
                "same_billing_shipping": fraud_analysis.same_billing_shipping,
                "shipping_state": fraud_analysis.shipping_state if hasattr(fraud_analysis, 'shipping_state') else None,
                "current_delivery_status": fraud_analysis.current_order_delivery_status,
                "days_since_last_delivery": getattr(fraud_analysis, 'days_since_last_delivery', None),
                "customer_total_orders": getattr(fraud_analysis, 'customer_total_orders', None),
                
                # Delivery analytics fields
                "delivery_success_rate": delivery_history.get('delivery_success_rate', 0.0),
                "average_delivery_days": delivery_history.get('average_delivery_days'),
                "total_orders": delivery_history.get('total_orders', 0),
                "delivered_orders": delivery_history.get('delivered_orders', 0),
                "failed_deliveries": delivery_history.get('failed_deliveries', 0),
                
                # Additional context
                "analysis_timestamp": fraud_analysis.analysis_timestamp,
                "store_id": fraud_analysis.store_id,
                "user_id": fraud_analysis.user_id,
                
                # Previous order cancellation status
                "previous_order_cancelled": getattr(fraud_analysis, 'previous_order_cancelled', None)
            }
            
            debug_log(logger, f"  CONVERTED DATA:")
            debug_log(logger, f"  - duplicate_within_7days (CONVERTED): {fraud_data.get('duplicate_within_7days')}")
            debug_log(logger, f"  - customer_name (CONVERTED): {fraud_data.get('customer_name')}")
            debug_log(logger, f"  - first_time_customer (CONVERTED): {fraud_data.get('first_time_customer')}")
            debug_log(logger, f"  - fraud_risk_level (CONVERTED): {fraud_data.get('fraud_risk_level')}")
            debug_log(logger, f"  - days_since_last_delivery (CONVERTED): {fraud_data.get('days_since_last_delivery')}")
            debug_log(logger, f"  - customer_total_orders (CONVERTED): {fraud_data.get('customer_total_orders')}")
            debug_log(logger, f"  - shipping_state (CONVERTED): {fraud_data.get('shipping_state')}")
            debug_log(logger, f"  - previous_order_cancelled (CONVERTED): {fraud_data.get('previous_order_cancelled')}")

            debug_log(logger, f"Converted fraud analysis to rule data: {len(fraud_data)} fields available")

            debug_log(logger, f"FRAUD DATA READY FOR RULE ENGINE:")
            debug_log(logger, f"  - duplicate_within_7days: {fraud_data.get('duplicate_within_7days')}")
            debug_log(logger, f"  - Type: {type(fraud_data.get('duplicate_within_7days'))}")
            
            return fraud_data
            
        except Exception as e:
            logger.error(f"Error converting fraud analysis to rule data: {str(e)}")
            return {
                "fraud_analysis_id": fraud_analysis.id if fraud_analysis else None,
                "order_name": fraud_analysis.order_name if fraud_analysis else "Unknown",
                "error": f"Data conversion failed: {str(e)}"
            }
    
    async def _execute_fraud_action(self, action: Dict[str, Any], fraud_data: Dict[str, Any], order_name: str, rule_name: str) -> Dict[str, Any]:
        """Execute a fraud detection action.
        
        Args:
            action: Action dictionary from rule
            fraud_data: Fraud analysis data
            order_name: Order name for logging
            rule_name: Rule name for context
            
        Returns:
            Dictionary with action execution results
        """
        action_type = action.get("type", "unknown")
        parameters = action.get("parameters", {})
        
        try:
            logger.info(f"Executing fraud action '{action_type}' for order {order_name} (rule: {rule_name})")
            
            if action_type == "do_nothing":
                return self._action_do_nothing(parameters, fraud_data, order_name, rule_name)
            elif action_type == "add_tag":
                return await self._action_add_tag(parameters, fraud_data, order_name, rule_name)
            elif action_type == "remove_tag":
                return await self._action_remove_tag(parameters, fraud_data, order_name, rule_name)
            elif action_type == "place_on_hold":
                return await self._action_place_on_hold(parameters, fraud_data, order_name, rule_name)
            else:
                logger.warning(f"Unknown fraud action type: {action_type}")
                return {
                    "type": action_type,
                    "success": False,
                    "error": f"Unknown action type: {action_type}"
                }
                
        except Exception as e:
            logger.error(f"Error executing fraud action '{action_type}': {str(e)}")
            return {
                "type": action_type,
                "success": False,
                "error": str(e)
            }
    
    def _action_do_nothing(self, parameters: Dict[str, Any], fraud_data: Dict[str, Any], order_name: str, rule_name: str) -> Dict[str, Any]:
        """Execute do_nothing action - just logs the action."""
        logger.info(f"Fraud rule '{rule_name}' executed do_nothing action for order {order_name}")
        
        return {
            "type": "do_nothing",
            "success": True,
            "message": f"Do nothing action executed by rule '{rule_name}'"
        }
    
    async def _action_add_tag(self, parameters: Dict[str, Any], fraud_data: Dict[str, Any], order_name: str, rule_name: str) -> Dict[str, Any]:
        """Execute add_tag action using Shopify client."""
        tags = parameters.get("tags", [])
        if not tags:
            return {
                "type": "add_tag",
                "success": False,
                "error": "No tags specified"
            }
        
        # Get order ID from fraud_data
        order_id = fraud_data.get("order_id")
        if not order_id:
            return {
                "type": "add_tag",
                "success": False,
                "error": "Order ID not available in fraud data"
            }
        
        try:
            # Use Shopify client to add tags
            success = await self.shopify_client.add_tags_to_order(order_id, tags)
            
            if success:
                logger.info(f"Successfully added tags {tags} to order {order_name} (rule: {rule_name})")
                return {
                    "type": "add_tag",
                    "success": True,
                    "tags": tags,
                    "order_id": order_id
                }
            else:
                logger.error(f"Failed to add tags {tags} to order {order_name} (rule: {rule_name})")
                return {
                    "type": "add_tag",
                    "success": False,
                    "error": "Shopify API call failed"
                }
                
        except Exception as e:
            logger.error(f"Error adding tags to order {order_name}: {str(e)}")
            return {
                "type": "add_tag",
                "success": False,
                "error": str(e)
            }
    
    async def _action_remove_tag(self, parameters: Dict[str, Any], fraud_data: Dict[str, Any], order_name: str, rule_name: str) -> Dict[str, Any]:
        """Execute remove_tag action using Shopify client."""
        tags = parameters.get("tags", [])
        if not tags:
            return {
                "type": "remove_tag",
                "success": False,
                "error": "No tags specified"
            }
        
        # Get order ID from fraud_data
        order_id = fraud_data.get("order_id")
        if not order_id:
            return {
                "type": "remove_tag",
                "success": False,
                "error": "Order ID not available in fraud data"
            }
        
        try:
            # Use Shopify client to remove tags
            success = await self.shopify_client.remove_tags_from_order(order_id, tags)
            
            if success:
                logger.info(f"Successfully removed tags {tags} from order {order_name} (rule: {rule_name})")
                return {
                    "type": "remove_tag",
                    "success": True,
                    "tags": tags,
                    "order_id": order_id
                }
            else:
                logger.error(f"Failed to remove tags {tags} from order {order_name} (rule: {rule_name})")
                return {
                    "type": "remove_tag",
                    "success": False,
                    "error": "Shopify API call failed"
                }
                
        except Exception as e:
            logger.error(f"Error removing tags from order {order_name}: {str(e)}")
            return {
                "type": "remove_tag",
                "success": False,
                "error": str(e)
            }
    
    async def _action_place_on_hold(self, parameters: Dict[str, Any], fraud_data: Dict[str, Any], order_name: str, rule_name: str) -> Dict[str, Any]:
        """Execute place_on_hold action using Shopify client."""
        # Get order ID from fraud_data
        order_id = fraud_data.get("order_id")
        if not order_id:
            return {
                "type": "place_on_hold",
                "success": False,
                "error": "Order ID not available in fraud data"
            }
        
        try:
            # Get fulfillment orders for this order
            fulfillment_orders = await self.shopify_client.get_fulfillment_orders_for_order(order_id)
            
            if not fulfillment_orders:
                logger.warning(f"No fulfillment orders found for order {order_name}. Order may be too new or already fulfilled.")
                return {
                    "type": "place_on_hold",
                    "success": False,
                    "error": "No fulfillment orders available for hold"
                }
            
            # Apply hold to the first available fulfillment order
            # Use the first fulfillment order that is not already on hold
            hold_applied = False
            errors = []
            
            for fulfillment_order in fulfillment_orders:
                fo_id = fulfillment_order.get("id")
                fo_status = fulfillment_order.get("status", "").upper()
                
                # Skip if already on hold or in a state that can't be held
                if fo_status in ["ON_HOLD", "CANCELLED", "CLOSED", "INCOMPLETE"]:
                    logger.debug(f"Skipping fulfillment order {fo_id} with status {fo_status}")
                    continue
                
                # Apply hold with fraud reason and rule context
                result = await self.shopify_client.apply_fulfillment_hold(
                    fulfillment_order_id=fo_id,
                    reason="HIGH_RISK_OF_FRAUD",
                    reason_notes=f"Fraud rule '{rule_name}' triggered",
                    notify_merchant=True
                )
                
                if result.get("success"):
                    hold_applied = True
                    logger.info(f"Successfully placed hold on order {order_name} (fulfillment order: {fo_id}) due to fraud rule '{rule_name}'")
                    
                    return {
                        "type": "place_on_hold",
                        "success": True,
                        "fulfillment_order_id": fo_id,
                        "hold_reason": "HIGH_RISK_OF_FRAUD",
                        "message": f"Order placed on hold due to fraud rule '{rule_name}'"
                    }
                else:
                    error_msg = result.get("errors", [{"message": "Unknown error"}])[0].get("message", "Unknown error")
                    errors.append(f"FO {fo_id}: {error_msg}")
                    logger.warning(f"Failed to place hold on fulfillment order {fo_id}: {error_msg}")
            
            # If we couldn't apply hold to any fulfillment order
            if not hold_applied:
                error_summary = "Failed to place hold on any fulfillment order. " + "; ".join(errors) if errors else "No eligible fulfillment orders found."
                logger.error(f"Could not place hold on order {order_name}: {error_summary}")
                
                return {
                    "type": "place_on_hold",
                    "success": False,
                    "error": error_summary
                }
                
        except Exception as e:
            logger.error(f"Error placing hold on order {order_name}: {str(e)}")
            
            return {
                "type": "place_on_hold",
                "success": False,
                "error": str(e)
            }
    
    def _update_fraud_analysis_with_results(self, fraud_analysis: FraudAnalysis, results: Dict[str, Any]) -> None:
        """Update FraudAnalysis record with rule processing results.
        
        Args:
            fraud_analysis: FraudAnalysis record to update
            results: Processing results from fraud rule evaluation
        """
        try:
            # Extract triggered rule IDs
            triggered_rule_ids = [
                result["rule_id"] for result in results["results"] 
                if result.get("matched", False)
            ]
            
            original_risk_level = fraud_analysis.shopify_fraud_risk_level
            debug_log(logger, f"FRAUD RULE PROCESSOR DEBUG - Analysis {fraud_analysis.id}: Original risk level: {original_risk_level}")

            # Don't override Shopify's original fraud risk assessment
            # Keep the original Shopify fraud risk level from the analysis

            # Update the fraud analysis record
            fraud_analysis.rule_triggered_ids = triggered_rule_ids if triggered_rule_ids else None
            fraud_analysis.rule_processing_results = results
            # DON'T override shopify_fraud_risk_level - keep Shopify's original assessment

            current_risk_level = fraud_analysis.shopify_fraud_risk_level
            debug_log(logger, f"FRAUD RULE PROCESSOR DEBUG - Analysis {fraud_analysis.id}: Current risk level: {current_risk_level}")

            if original_risk_level != current_risk_level:
                logger.error(f"FRAUD RULE PROCESSOR BUG - Analysis {fraud_analysis.id}: Risk level changed from {original_risk_level} to {current_risk_level}!")

            # Commit the changes
            self.db.commit()

            self.db.refresh(fraud_analysis)
            post_commit_risk_level = fraud_analysis.shopify_fraud_risk_level
            debug_log(logger, f"FRAUD RULE PROCESSOR DEBUG - Analysis {fraud_analysis.id}: Post-commit risk level: {post_commit_risk_level}")

            if original_risk_level != post_commit_risk_level:
                logger.error(f"FRAUD RULE PROCESSOR BUG - Analysis {fraud_analysis.id}: Risk level changed after commit from {original_risk_level} to {post_commit_risk_level}!")
            
            logger.info(f"Updated fraud analysis {fraud_analysis.id} with rule results: "
                       f"{len(triggered_rule_ids)} rules triggered")
                       
        except Exception as e:
            logger.error(f"Error updating fraud analysis with rule results: {str(e)}")
            self.db.rollback()


async def process_fraud_rules_for_order_async(
    db: Session, 
    user: User, 
    store: ShopifyStore, 
    shopify_client,
    order_data: Dict[str, Any], 
    fraud_analysis: FraudAnalysis
) -> Dict[str, Any]:
    """Async wrapper for fraud rule processing.
    
    Args:
        db: Database session
        user: User instance
        store: ShopifyStore instance
        shopify_client: ShopifyClient instance for API calls
        order_data: Raw order data from Shopify
        fraud_analysis: FraudAnalysis record for the order
        
    Returns:
        Dictionary with processing results
    """
    try:
        processor = FraudRuleProcessor(db, user, store, shopify_client)
        return await processor.process_fraud_rules_for_order(order_data, fraud_analysis)
    except Exception as e:
        logger.error(f"Error in async fraud rule processing: {str(e)}")
        return {
            "rules_processed": 0,
            "rules_matched": 0,
            "actions_executed": 0,
            "results": [],
            "error": str(e)
        }