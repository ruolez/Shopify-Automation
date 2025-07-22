#!/usr/bin/env python
"""Debug script to check fraud duplicate detection and rule evaluation"""

import sys
from sqlalchemy.orm import Session
from database import get_db
from models import User, FraudAnalysis, FraudDetectionRule, Settings

def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_fraud_duplicate.py <user_id>")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    db = next(get_db())
    
    try:
        # Get user settings
        settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        print(f"\n🔍 User {user_id} Settings:")
        print(f"  - duplicate_detection_days: {settings.duplicate_detection_days if settings else 'Not set (default: 7)'}")
        
        # Get fraud rules checking duplicate
        fraud_rules = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.user_id == user_id,
            FraudDetectionRule.is_active == True
        ).all()
        
        print(f"\n📋 Active Fraud Rules: {len(fraud_rules)}")
        for rule in fraud_rules:
            conditions = rule.conditions or {}
            if isinstance(conditions, dict):
                conditions_list = conditions.get('conditions', [])
            else:
                conditions_list = conditions if isinstance(conditions, list) else []
            
            # Check if any condition uses duplicate_within_7days
            for condition in conditions_list:
                if condition.get('field') == 'duplicate_within_7days':
                    print(f"\n  Rule: {rule.name}")
                    print(f"    - Field: {condition.get('field')}")
                    print(f"    - Operator: {condition.get('operator')}")
                    print(f"    - Value: {condition.get('value')} (type: {type(condition.get('value'))})")
        
        # Get recent fraud analyses
        analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id
        ).order_by(FraudAnalysis.analysis_timestamp.desc()).limit(10).all()
        
        print(f"\n📊 Recent Fraud Analyses:")
        for analysis in analyses:
            print(f"\n  Order: {analysis.order_name}")
            print(f"    - duplicate_within_7days: {analysis.duplicate_within_7days}")
            print(f"    - rule_triggered_ids: {analysis.rule_triggered_ids}")
            
            # Check if any fraud rules were triggered
            if analysis.rule_processing_results:
                results = analysis.rule_processing_results
                if isinstance(results, dict) and 'results' in results:
                    for rule_result in results['results']:
                        if rule_result.get('matched'):
                            print(f"    - Matched Rule: {rule_result.get('rule_name')}")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()