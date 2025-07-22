#!/usr/bin/env python3
"""
Test fraud rule processing for a specific order
"""

import sys
import os
import asyncio
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import User, ShopifyStore, FraudAnalysis, FraudDetectionRule, OrderLog
from fraud_rule_processor import FraudRuleProcessor
from rule_engine import RuleEngine

async def test_fraud_rules():
    db = SessionLocal()
    try:
        # Get the fraud analysis for PW110550
        fraud_analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.order_name == "PW110550"
        ).first()
        
        if not fraud_analysis:
            print("No fraud analysis found for order PW110550")
            return
            
        print(f"Found fraud analysis ID: {fraud_analysis.id}")
        print(f"Risk Level: {fraud_analysis.shopify_fraud_risk_level}")
        print(f"Age Checker: {fraud_analysis.age_checker_detected}")
        print(f"Order Total: {fraud_analysis.order_total}")
        
        # Get store and user
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == fraud_analysis.store_id
        ).first()
        
        user = db.query(User).filter(
            User.id == fraud_analysis.user_id
        ).first()
        
        # Initialize fraud rule processor
        processor = FraudRuleProcessor(db, user, store)
        
        # Create mock order data (minimal required for rule processing)
        order_data = {
            "name": "PW110550",
            "id": "gid://shopify/Order/12345",
            "order_info": {
                "name": "PW110550",
                "id": "gid://shopify/Order/12345"
            }
        }
        
        # Test the conversion function first
        print("\n=== Testing Fraud Data Conversion ===")
        fraud_data = processor._convert_fraud_analysis_to_rule_data(fraud_analysis)
        print(f"fraud_risk_level: {fraud_data.get('fraud_risk_level')}")
        print(f"age_checker_detected: {fraud_data.get('age_checker_detected')}")
        print(f"order_total: {fraud_data.get('order_total')}")
        
        # Test individual rules
        print("\n=== Testing Individual Rules ===")
        rule_engine = RuleEngine(db)
        
        # Test Low risk rule
        low_risk_rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.id == 5  # Low risk rule
        ).first()
        
        if low_risk_rule:
            print(f"\nTesting rule: {low_risk_rule.name}")
            print(f"Conditions: {json.dumps(low_risk_rule.conditions, indent=2)}")
            matched = rule_engine.evaluate_rule(low_risk_rule, fraud_data)
            print(f"Rule matched: {matched}")
            
            # Test the specific condition
            print(f"\nDirect test of risk_level_equals:")
            print(f"  Actual value: '{fraud_data.get('fraud_risk_level')}'")
            print(f"  Expected value: 'LOW'")
            print(f"  Comparison result: {fraud_data.get('fraud_risk_level') == 'LOW'}")
        
        # Test Age checker rule
        age_rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.id == 4  # Age checker rule
        ).first()
        
        if age_rule:
            print(f"\nTesting rule: {age_rule.name}")
            print(f"Conditions: {json.dumps(age_rule.conditions, indent=2)}")
            matched = rule_engine.evaluate_rule(age_rule, fraud_data)
            print(f"Rule matched: {matched}")
            
            # Test the specific condition
            print(f"\nDirect test of age_checker_detected:")
            print(f"  Actual value: {fraud_data.get('age_checker_detected')} (type: {type(fraud_data.get('age_checker_detected'))})")
            print(f"  Expected value: true (type: bool)")
            print(f"  Comparison result: {fraud_data.get('age_checker_detected') == True}")
        
        # Test Over $150 rule
        over_150_rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.id == 3  # Over $150 rule
        ).first()
        
        if over_150_rule:
            print(f"\nTesting rule: {over_150_rule.name}")
            print(f"Conditions: {json.dumps(over_150_rule.conditions, indent=2)}")
            matched = rule_engine.evaluate_rule(over_150_rule, fraud_data)
            print(f"Rule matched: {matched}")
            
            # Test the specific condition
            print(f"\nDirect test of order_total > 150:")
            print(f"  Actual value: {fraud_data.get('order_total')} (type: {type(fraud_data.get('order_total'))})")
            print(f"  Expected value: 150")
            print(f"  Comparison result: {fraud_data.get('order_total') > 150}")
        
        # Now run the full fraud rule processing
        print("\n=== Running Full Fraud Rule Processing ===")
        result = await processor.process_fraud_rules_for_order(order_data, fraud_analysis)
        
        print(f"\nProcessing Results:")
        print(f"Rules processed: {result.get('rules_processed', 0)}")
        print(f"Rules matched: {result.get('rules_matched', 0)}")
        print(f"Actions executed: {result.get('actions_executed', 0)}")
        
        if 'results' in result:
            for rule_result in result['results']:
                print(f"\nRule: {rule_result.get('rule_name')} (ID: {rule_result.get('rule_id')})")
                print(f"  Matched: {rule_result.get('matched')}")
                if 'error' in rule_result:
                    print(f"  Error: {rule_result.get('error')}")
                    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_fraud_rules())