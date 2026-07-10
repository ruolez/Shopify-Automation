#!/usr/bin/env python3
"""Check fraud analysis for order TS8305842"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudAnalysis
import json

db = SessionLocal()
try:
    # Find fraud analysis for TS8305842
    analysis = db.query(FraudAnalysis).filter(
        FraudAnalysis.order_name == "TS8305842"
    ).order_by(FraudAnalysis.analysis_timestamp.desc()).first()
    
    if analysis:
        print(f"Found fraud analysis for order TS8305842")
        print(f"Analysis ID: {analysis.id}")
        print(f"Age Checker Detected: {analysis.age_checker_detected}")
        print(f"Customer Notes: {analysis.customer_notes}")
        print(f"Additional Details: {analysis.additional_details}")
        print(f"Shopify Fraud Risk Level: {analysis.shopify_fraud_risk_level}")
        print(f"Analysis Timestamp: {analysis.analysis_timestamp}")
        
        # Check if the NoAge rule should have matched
        print("\n--- Should NoAge rule match? ---")
        print(f"age_checker_detected = {analysis.age_checker_detected}")
        print(f"Expected for match: age_checker_detected = False")
        print(f"Should match: {analysis.age_checker_detected == False}")
        
        if analysis.rule_processing_results:
            print("\nRule Processing Results:")
            results = analysis.rule_processing_results
            if isinstance(results, dict):
                print(f"Rules Processed: {results.get('rules_processed', 0)}")
                print(f"Rules Matched: {results.get('rules_matched', 0)}")
                
                # Check NoAge rule specifically
                noage_found = False
                for rule_result in results.get('results', []):
                    if rule_result.get('rule_name') == 'NoAge':
                        noage_found = True
                        print(f"\nNoAge rule result:")
                        print(f"  - Matched: {rule_result.get('matched')}")
                        print(f"  - Error: {rule_result.get('error', 'None')}")
                        if rule_result.get('actions'):
                            print(f"  - Actions: {rule_result.get('actions')}")
                
                if not noage_found:
                    print("\nNoAge rule was not found in processing results!")
                    
                # Show all matched rules
                print(f"\nMatched rules:")
                for rule_result in results.get('results', []):
                    if rule_result.get('matched'):
                        print(f"  - Rule '{rule_result.get('rule_name')}' matched")
    else:
        print("No fraud analysis found for order TS8305842")
        
finally:
    db.close()