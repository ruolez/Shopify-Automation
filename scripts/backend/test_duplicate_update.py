#!/usr/bin/env python
"""Test script to manually update duplicate detection and verify rule matching"""

import sys
from sqlalchemy.orm import Session
from database import get_db
from models import User, FraudAnalysis, Settings

def main():
    if len(sys.argv) < 3:
        print("Usage: python test_duplicate_update.py <user_id> <order_name>")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    order_name = sys.argv[2]
    db = next(get_db())
    
    try:
        # Get the fraud analysis
        analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.order_name == order_name
        ).first()
        
        if not analysis:
            print(f"❌ No fraud analysis found for order {order_name}")
            return
        
        print(f"\n📊 Fraud Analysis for {order_name}:")
        print(f"  - Current duplicate_within_7days: {analysis.duplicate_within_7days}")
        print(f"  - Rule triggered IDs: {analysis.rule_triggered_ids}")
        
        # Toggle the duplicate value
        new_value = not analysis.duplicate_within_7days
        analysis.duplicate_within_7days = new_value
        db.commit()
        
        print(f"\n✅ Updated duplicate_within_7days to: {new_value}")
        
        # Refresh to verify
        db.refresh(analysis)
        print(f"  - Verified in DB: {analysis.duplicate_within_7days}")
        
        print("\n💡 Now run 'Reprocess Fraud Rules' to see if the rule matches based on the new value")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()