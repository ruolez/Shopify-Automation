#!/usr/bin/env python3
"""
Check fraud detection rules and their conditions
"""

import sys
import os
import json

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudDetectionRule, User, ShopifyStore

def check_fraud_rules():
    db = SessionLocal()
    try:
        # Get primewholesale store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == "primewholesale-com.myshopify.com"
        ).first()
        
        if not store:
            print("Store not found!")
            return
            
        # Get all fraud detection rules for this user
        fraud_rules = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.user_id == store.user_id,
            FraudDetectionRule.is_active == True
        ).order_by(FraudDetectionRule.priority).all()
        
        print(f"Found {len(fraud_rules)} active fraud detection rules for user {store.user_id}")
        print("=" * 80)
        
        for rule in fraud_rules:
            print(f"\nRule: {rule.name} (ID: {rule.id}, Priority: {rule.priority})")
            print(f"Description: {rule.description}")
            print(f"Conditions:")
            print(json.dumps(rule.conditions, indent=2))
            print(f"Actions:")
            print(json.dumps(rule.actions, indent=2))
            print("-" * 40)
            
            # Check for specific conditions we're interested in
            conditions_str = json.dumps(rule.conditions)
            if "fraud_risk_level" in conditions_str and "LOW" in conditions_str:
                print("✅ This rule checks for LOW fraud risk level")
            if "age_checker_detected" in conditions_str:
                print("✅ This rule checks for age checker detected")
                
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_fraud_rules()