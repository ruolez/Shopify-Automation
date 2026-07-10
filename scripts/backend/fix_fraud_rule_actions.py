#!/usr/bin/env python3
"""
Script to fix fraud rule actions that incorrectly use 'do_nothing' with tag parameters.
This will convert them to proper 'add_tag' actions.
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
                # If action is do_nothing but has tags parameter, convert to add_tag
                if action.get('type') == 'do_nothing' and action.get('parameters', {}).get('tags'):
                    print(f"Fixing rule '{rule.name}' (ID: {rule.id})")
                    print(f"  Old action: {action}")
                    
                    # Convert to add_tag action
                    tags_value = action['parameters']['tags']
                    # Convert single tag string to list
                    if isinstance(tags_value, str):
                        tags_list = [tag.strip() for tag in tags_value.split(',')]
                    else:
                        tags_list = tags_value
                    
                    rule.actions[i] = {
                        'type': 'add_tag',
                        'parameters': {
                            'tags': tags_list
                        }
                    }
                    
                    print(f"  New action: {rule.actions[i]}")
                    updated = True
                    fixed_count += 1
            
            if updated:
                db.commit()
                print(f"  ✓ Updated rule '{rule.name}'")
                print()
        
        print(f"\nFixed {fixed_count} fraud rule actions")
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    fix_fraud_rule_actions()