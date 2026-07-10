#!/usr/bin/env python3
"""Check fraud analysis for order TG54276"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudAnalysis
import json

db = SessionLocal()
try:
    # Find fraud analysis for TG54276
    analysis = db.query(FraudAnalysis).filter(
        FraudAnalysis.order_name == "TG54276"
    ).order_by(FraudAnalysis.analysis_timestamp.desc()).first()
    
    if analysis:
        print(f"Found fraud analysis for order TG54276")
        print(f"Analysis ID: {analysis.id}")
        print(f"Age Checker Detected: {analysis.age_checker_detected}")
        print(f"Customer Notes: {analysis.customer_notes}")
        print(f"Additional Details: {analysis.additional_details}")
        print(f"Shopify Fraud Risk Level: {analysis.shopify_fraud_risk_level}")
        print(f"Analysis Timestamp: {analysis.analysis_timestamp}")
        
        if analysis.rule_processing_results:
            print("\nRule Processing Results:")
            results = analysis.rule_processing_results
            if isinstance(results, dict):
                print(f"Rules Processed: {results.get('rules_processed', 0)}")
                print(f"Rules Matched: {results.get('rules_matched', 0)}")
                
                for rule_result in results.get('results', []):
                    if rule_result.get('matched'):
                        print(f"  - Rule '{rule_result.get('rule_name')}' matched")
    else:
        print("No fraud analysis found for order TG54276")
        
finally:
    db.close()