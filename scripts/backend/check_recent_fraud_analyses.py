#!/usr/bin/env python3
"""Check recent fraud analyses for age checker false negatives"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudAnalysis
from datetime import datetime, timedelta, timezone

db = SessionLocal()
try:
    # Get recent analyses from the last 30 minutes
    recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    analyses = db.query(FraudAnalysis).filter(
        FraudAnalysis.analysis_timestamp >= recent_time
    ).order_by(FraudAnalysis.analysis_timestamp.desc()).all()
    
    print(f"Found {len(analyses)} recent fraud analyses")
    print("-" * 80)
    
    false_negative_count = 0
    for analysis in analyses:
        has_age_checker_text = False
        age_checker_location = None
        
        # Check for age checker text in customer notes
        if analysis.customer_notes:
            notes_lower = analysis.customer_notes.lower()
            if any(pattern in notes_lower for pattern in ['age-checker', 'agechecker', 'age_checker', 'age checker']):
                has_age_checker_text = True
                age_checker_location = "customer_notes"
        
        # Check for age checker text in additional details
        if analysis.additional_details:
            details_lower = analysis.additional_details.lower()
            if any(pattern in details_lower for pattern in ['age-checker', 'agechecker', 'age_checker', 'age checker']):
                has_age_checker_text = True
                age_checker_location = "additional_details"
            
        if has_age_checker_text and not analysis.age_checker_detected:
            false_negative_count += 1
            print(f"❌ FALSE NEGATIVE - Order: {analysis.order_name}")
            print(f"   Age Checker Detected: {analysis.age_checker_detected}")
            print(f"   Age checker found in: {age_checker_location}")
            print(f"   Customer Notes: {analysis.customer_notes}")
            print(f"   Additional Details: {analysis.additional_details[:200] if analysis.additional_details else None}")
            print("-" * 40)
    
    # Also show some true positives for comparison
    true_positive_count = 0
    print("\n✅ TRUE POSITIVES (for comparison):")
    for analysis in analyses:
        if analysis.age_checker_detected:
            true_positive_count += 1
            if true_positive_count <= 3:  # Show first 3
                print(f"   Order: {analysis.order_name}")
                print(f"   Customer Notes: {analysis.customer_notes}")
                print(f"   Additional Details: {analysis.additional_details[:100] if analysis.additional_details else None}")
                print("-" * 40)
    
    print(f"\nSummary:")
    print(f"Total analyses: {len(analyses)}")
    print(f"False negatives: {false_negative_count}")
    print(f"True positives: {true_positive_count}")
    
finally:
    db.close()