#!/usr/bin/env python3
"""
Script to remove unnecessary parameters from 'do_nothing' fraud rule actions.
The parameters were added by users because the UI had a parameter field, but do_nothing doesn't use them.
"""

from database import SessionLocal
from models import FraudDetectionRule
import json

def fix_fraud_rule_actions():
    db = SessionLocal()
    
    try:
        # Get all fraud rules
        rules = db.query(FraudDetectionRule).all()
        
        fixed_count = 0
        
        for rule in rules:
            updated = False
            
            # Check each action
            for i, action in enumerate(rule.actions):
                # If action is do_nothing, remove any parameters
                if action.get('type') == 'do_nothing' and action.get('parameters'):
                    print(f"Fixing rule '{rule.name}' (ID: {rule.id})")
                    print(f"  Old action: {action}")
                    
                    # Keep do_nothing but remove parameters
                    rule.actions[i] = {
                        'type': 'do_nothing',
                        'parameters': {}
                    }
                    
                    print(f"  New action: {rule.actions[i]}")
                    updated = True
                    fixed_count += 1
            
            if updated:
                db.commit()
                print(f"  ✓ Updated rule '{rule.name}'")
                print()
        
        print(f"\nFixed {fixed_count} fraud rule actions by removing unnecessary parameters")
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    fix_fraud_rule_actions()