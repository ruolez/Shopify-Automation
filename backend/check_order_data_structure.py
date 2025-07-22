#!/usr/bin/env python3
"""Check the actual order data structure in the database"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudAnalysis
import json

db = SessionLocal()
try:
    # Get a few recent fraud analyses with age-checker in notes
    analyses = db.query(FraudAnalysis).filter(
        FraudAnalysis.customer_notes.like('%age-checker%')
    ).limit(5).all()
    
    print(f"Found {len(analyses)} analyses with age-checker in customer notes")
    print("-" * 80)
    
    for analysis in analyses:
        print(f"\nOrder: {analysis.order_name}")
        print(f"Age Checker Detected: {analysis.age_checker_detected}")
        print(f"Customer Notes: {analysis.customer_notes}")
        print(f"Additional Details: {analysis.additional_details}")
        
        # Try to parse the order data if stored
        if analysis.order_data:
            try:
                order_data = json.loads(analysis.order_data)
                custom_attrs = order_data.get('customAttributes', [])
                print(f"Custom Attributes from order_data: {custom_attrs}")
            except:
                print("Could not parse order_data")
        
        print("-" * 80)
        
finally:
    db.close()