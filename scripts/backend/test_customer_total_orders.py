#!/usr/bin/env python3
"""
Test script to verify customer_total_orders field is being extracted and passed correctly.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from database import SessionLocal
from models import FraudAnalysis, FraudDetectionRule, User, ShopifyStore
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_customer_total_orders():
    """Test the customer_total_orders field in fraud analysis and rule evaluation."""
    db = SessionLocal()
    
    try:
        # 1. Check if the field exists in the latest fraud analysis
        latest_analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.order_name == "TG54608"
        ).order_by(FraudAnalysis.id.desc()).first()
        
        if not latest_analysis:
            logger.error("No fraud analysis found for order TG54608")
            return
            
        logger.info(f"Found fraud analysis ID: {latest_analysis.id}")
        logger.info(f"Order: {latest_analysis.order_name}")
        logger.info(f"customer_total_orders value: {latest_analysis.customer_total_orders}")
        logger.info(f"Type: {type(latest_analysis.customer_total_orders)}")
        
        # 2. Check the fraud rule
        rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.name == "3+ Orders"
        ).first()
        
        if not rule:
            logger.error("No fraud rule found with name '3+ Orders'")
            return
            
        logger.info(f"\nFraud Rule ID: {rule.id}")
        logger.info(f"Rule conditions: {rule.conditions}")
        logger.info(f"Rule is_active: {rule.is_active}")
        
        # 3. Test the rule engine conversion
        from fraud_rule_processor import FraudRuleProcessor
        
        # Get user and store
        user = db.query(User).filter(User.id == latest_analysis.user_id).first()
        store = db.query(ShopifyStore).filter(ShopifyStore.id == latest_analysis.store_id).first()
        
        if not user or not store:
            logger.error("User or store not found")
            return
            
        # Create processor (we don't need shopify_client for this test)
        processor = FraudRuleProcessor(db, user, store, None)
        
        # Test the conversion
        fraud_data = processor._convert_fraud_analysis_to_rule_data(latest_analysis)
        
        logger.info(f"\nConverted fraud data:")
        logger.info(f"customer_total_orders in fraud_data: {fraud_data.get('customer_total_orders')}")
        logger.info(f"Type: {type(fraud_data.get('customer_total_orders'))}")
        
        # 4. Test rule evaluation directly
        from rule_engine import RuleEngine
        rule_engine = RuleEngine(db)
        
        logger.info(f"\nTesting rule evaluation:")
        matched = rule_engine.evaluate_rule(rule, fraud_data)
        logger.info(f"Rule matched: {matched}")
        
        # 5. Check the specific condition evaluation
        if rule.conditions and isinstance(rule.conditions, dict):
            conditions = rule.conditions.get('conditions', [])
            if conditions:
                condition = conditions[0]
                field = condition.get('field')
                operator = condition.get('operator')
                value = condition.get('value')
                
                logger.info(f"\nCondition details:")
                logger.info(f"Field: {field}")
                logger.info(f"Operator: {operator}")
                logger.info(f"Expected value: {value} (type: {type(value)})")
                logger.info(f"Actual value: {fraud_data.get(field)} (type: {type(fraud_data.get(field))})")
                
                # Test comparison
                if operator == 'greater_than':
                    actual_val = fraud_data.get(field)
                    if actual_val is not None:
                        try:
                            expected_val = float(value) if value is not None else 0
                            actual_val = float(actual_val)
                            result = actual_val > expected_val
                            logger.info(f"Comparison: {actual_val} > {expected_val} = {result}")
                        except Exception as e:
                            logger.error(f"Comparison error: {e}")
                    else:
                        logger.error("Actual value is None!")
        
    except Exception as e:
        logger.error(f"Error in test: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    test_customer_total_orders()