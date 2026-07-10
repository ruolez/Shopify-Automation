#!/usr/bin/env python3
"""
Test fraud rule evaluation to debug why rules aren't matching
"""

from database import SessionLocal
from models import FraudAnalysis, FraudDetectionRule
from rule_engine import RuleEngine
from fraud_rule_processor import FraudRuleProcessor
import json

db = SessionLocal()

# Get a specific fraud analysis
analysis = db.query(FraudAnalysis).filter(FraudAnalysis.order_name == 'PW110537').first()

if analysis:
    print(f"Testing fraud analysis for order: {analysis.order_name}")
    print(f"Data:")
    print(f"  age_checker_detected: {analysis.age_checker_detected} (type: {type(analysis.age_checker_detected)})")
    print(f"  same_billing_shipping: {analysis.same_billing_shipping} (type: {type(analysis.same_billing_shipping)})")
    print(f"  fraud_risk_level: {analysis.shopify_fraud_risk_level} (type: {type(analysis.shopify_fraud_risk_level)})")
    print(f"  days_since_last_delivery: {analysis.days_since_last_delivery} (type: {type(analysis.days_since_last_delivery)})")
    print()
    
    # Get the fraud rules
    rules = db.query(FraudDetectionRule).filter(
        FraudDetectionRule.is_active == True
    ).order_by(FraudDetectionRule.priority).all()
    
    # Create rule engine
    rule_engine = RuleEngine(db)
    
    # Convert fraud analysis to rule data (simplified)
    fraud_data = {
        "age_checker_detected": analysis.age_checker_detected,
        "same_billing_shipping": analysis.same_billing_shipping,
        "fraud_risk_level": analysis.shopify_fraud_risk_level,
        "days_since_last_delivery": analysis.days_since_last_delivery,
        "order_total": float(analysis.order_total) if analysis.order_total else 0.0,
        "first_time_customer": analysis.is_first_time_customer,
        "duplicate_within_7days": analysis.duplicate_within_7days,
    }
    
    print("Converted fraud data:")
    print(json.dumps(fraud_data, indent=2))
    print()
    
    # Test each rule
    for rule in rules:
        print(f"\nTesting rule: {rule.name}")
        print(f"Conditions: {json.dumps(rule.conditions, indent=2)}")
        
        try:
            # Evaluate the rule
            result = rule_engine.evaluate_rule(rule, fraud_data)
            print(f"Result: {'MATCHED' if result else 'NOT MATCHED'}")
            
            # Test specific conditions manually
            if rule.name == "Age" and rule.conditions.get("conditions"):
                condition = rule.conditions["conditions"][0]
                field_value = fraud_data.get(condition["field"])
                expected_value = condition["value"]
                print(f"  Checking: {condition['field']} = {field_value} (type: {type(field_value)})")
                print(f"  Expected: {expected_value} (type: {type(expected_value)})")
                print(f"  Operator: {condition['operator']}")
                
        except Exception as e:
            print(f"Error evaluating rule: {e}")

db.close()