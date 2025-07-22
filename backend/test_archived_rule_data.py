#!/usr/bin/env python3
"""
Test if archived analyses have proper rule data in API response.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import requests
import json
from database import SessionLocal
from models import User
from auth import create_access_token

def test_archived_rule_data():
    """Test if archived analyses return proper rule data."""
    print("Testing archived analyses rule data...")
    
    # Get database session
    db = SessionLocal()
    
    try:
        # Get user with fraud analyses
        test_user = db.query(User).filter(User.id == 4).first()
        if not test_user:
            print("   ❌ Test user not found")
            return False
        
        token = create_access_token(data={"sub": test_user.email})
        headers = {"Authorization": f"Bearer {token}"}
        
        base_url = "http://localhost:8000"
        
        # Get archived analyses
        print(f"\\n1. Getting archived analyses...")
        response = requests.get(f"{base_url}/fraud-detection/archived-analyses", headers=headers)
        
        if response.status_code != 200:
            print(f"   ❌ Failed to get archived analyses: {response.status_code}")
            return False
        
        data = response.json()
        analyses = data.get('data', [])
        
        if not analyses:
            print("   ❌ No archived analyses found")
            return False
        
        print(f"   ✅ Found {len(analyses)} archived analyses")
        
        # Check rule data for each analysis
        print(f"\\n2. Checking rule data...")
        for analysis in analyses[:3]:  # Check first 3
            print(f"\\n   Order: {analysis['order_name']}")
            print(f"   - rule_triggered_ids: {analysis.get('rule_triggered_ids')}")
            
            rule_results = analysis.get('rule_processing_results')
            if rule_results:
                if isinstance(rule_results, str):
                    print(f"   - rule_processing_results is STRING (should be parsed JSON)")
                    try:
                        parsed = json.loads(rule_results)
                        print(f"   - After parsing: {len(parsed.get('results', []))} rules processed")
                    except:
                        print(f"   - Failed to parse JSON")
                elif isinstance(rule_results, dict):
                    print(f"   - rule_processing_results is DICT (correctly parsed)")
                    print(f"   - Contains {len(rule_results.get('results', []))} rule results")
                    
                    # Show matched rules
                    matched_rules = [r['rule_name'] for r in rule_results.get('results', []) if r.get('matched')]
                    if matched_rules:
                        print(f"   - Matched rules: {', '.join(matched_rules)}")
                    else:
                        print(f"   - No rules matched")
            else:
                print(f"   - rule_processing_results is NULL")
        
        print("\\n✅ Archived rule data test completed!")
        return True
        
    except Exception as e:
        print(f"\\n❌ Error during testing: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = test_archived_rule_data()
    sys.exit(0 if success else 1)