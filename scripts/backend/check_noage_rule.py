#!/usr/bin/env python3
"""Check the NoAge fraud rule conditions"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudDetectionRule
import json

db = SessionLocal()
try:
    # Find the NoAge rule
    rule = db.query(FraudDetectionRule).filter(
        FraudDetectionRule.name == "NoAge"
    ).first()
    
    if rule:
        print(f"Found 'NoAge' rule")
        print(f"Rule ID: {rule.id}")
        print(f"Is Active: {rule.is_active}")
        print(f"Priority: {rule.priority}")
        print(f"\nConditions:")
        print(json.dumps(rule.conditions, indent=2))
        print(f"\nActions:")
        print(json.dumps(rule.actions, indent=2))
    else:
        print("No 'NoAge' rule found")
        
        # List all fraud rules to help find the right one
        all_rules = db.query(FraudDetectionRule).all()
        print("\nAll fraud rules:")
        for r in all_rules:
            print(f"  - {r.name} (ID: {r.id}, Active: {r.is_active})")
        
finally:
    db.close()