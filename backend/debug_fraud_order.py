#!/usr/bin/env python3
"""
Debug fraud analysis for a specific order
"""

import sys
import os
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudAnalysis, FraudDetectionRule, OrderLog
from sqlalchemy import desc

def debug_order(order_name: str = "PW110550"):
    db = SessionLocal()
    try:
        # Find fraud analysis for this order
        fraud_analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.order_name == order_name
        ).first()
        
        if not fraud_analysis:
            print(f"No fraud analysis found for order {order_name}")
            return
            
        print(f"=== FRAUD ANALYSIS FOR ORDER {order_name} ===")
        print(f"Analysis ID: {fraud_analysis.id}")
        print(f"Store ID: {fraud_analysis.store_id}")
        print(f"Analysis Timestamp: {fraud_analysis.analysis_timestamp}")
        print(f"\nFRAUD INDICATORS:")
        print(f"  - Shopify Risk Level: {fraud_analysis.shopify_fraud_risk_level}")
        print(f"  - First Time Customer: {fraud_analysis.is_first_time_customer}")
        print(f"  - Order Total: ${fraud_analysis.order_total}")
        print(f"  - Duplicate Order: {fraud_analysis.duplicate_within_7days}")
        print(f"  - Age Checker Detected: {fraud_analysis.age_checker_detected}")
        print(f"  - Billing Outside US: {fraud_analysis.billing_address_outside_us}")
        print(f"  - Same Billing/Shipping: {fraud_analysis.same_billing_shipping}")
        print(f"  - Shipping State: {fraud_analysis.shipping_state}")
        print(f"  - Customer Name: {fraud_analysis.customer_name}")
        print(f"  - Transaction Attempts: {fraud_analysis.transaction_attempts_count}")
        
        # Check rule processing results
        if fraud_analysis.rule_processing_results:
            print(f"\n=== RULE PROCESSING RESULTS ===")
            results = fraud_analysis.rule_processing_results
            print(f"Rules Evaluated: {results.get('rules_evaluated', 0)}")
            print(f"Rules Matched: {results.get('rules_matched', 0)}")
            
            if 'evaluated_rules' in results:
                print("\nEVALUATED RULES:")
                for rule in results['evaluated_rules']:
                    print(f"\n  Rule: {rule.get('name')} (ID: {rule.get('id')})")
                    print(f"  Matched: {rule.get('matched')}")
                    if 'evaluation_details' in rule:
                        print(f"  Details: {json.dumps(rule['evaluation_details'], indent=4)}")
        
        # Get all fraud detection rules
        print(f"\n=== ACTIVE FRAUD DETECTION RULES ===")
        fraud_rules = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.user_id == fraud_analysis.user_id,
            FraudDetectionRule.is_active == True
        ).order_by(FraudDetectionRule.priority).all()
        
        print(f"Found {len(fraud_rules)} active fraud detection rules")
        
        for rule in fraud_rules[:5]:  # Show first 5
            print(f"\nRule: {rule.name} (ID: {rule.id}, Priority: {rule.priority})")
            print(f"Conditions: {json.dumps(rule.conditions, indent=2)}")
            
        # Check order logs for fraud processing
        print(f"\n=== ORDER LOGS FOR FRAUD PROCESSING ===")
        fraud_logs = db.query(OrderLog).filter(
            OrderLog.order_number == order_name,
            OrderLog.action.in_(['fraud_analysis_completed', 'fraud_rule_matched', 'fraud_alert', 'fraud_processing_error'])
        ).order_by(desc(OrderLog.created_at)).limit(10).all()
        
        if fraud_logs:
            for log in fraud_logs:
                print(f"\n{log.created_at}: {log.action} ({log.status})")
                if log.details:
                    print(f"Details: {json.dumps(log.details, indent=2)}")
                if log.error_message:
                    print(f"Error: {log.error_message}")
        else:
            print("No fraud-related logs found")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    order_name = sys.argv[1] if len(sys.argv) > 1 else "PW110550"
    debug_order(order_name)