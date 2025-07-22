#!/usr/bin/env python3
"""
Test script for manual archive functionality.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import requests
import json
from database import SessionLocal
from models import User, FraudAnalysis
from auth import create_access_token

def test_manual_archive():
    """Test the manual archive functionality."""
    print("Testing manual archive functionality...")
    
    # Get database session
    db = SessionLocal()
    
    try:
        # Get a test user who has fraud analyses
        test_user = db.query(User).filter(User.id == 4).first()  # alexr@tobaccogeneral.com has fraud analyses
        if not test_user:
            print("   ❌ Test user not found in database")
            return False
        
        token = create_access_token(data={"sub": test_user.email})
        headers = {"Authorization": f"Bearer {token}"}
        
        base_url = "http://localhost:8000"
        
        # Get an active fraud analysis to archive
        active_analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == test_user.id
        ).first()
        
        if not active_analysis:
            print("   ❌ No active fraud analyses found to test with")
            return False
        
        print(f"   Found analysis to archive: {active_analysis.order_name} (ID: {active_analysis.id})")
        
        # Test manual archive
        print(f"\\n1. Testing manual archive of analysis {active_analysis.id}...")
        response = requests.post(
            f"{base_url}/fraud-detection/archive/{active_analysis.id}?archive_reason=manual_archive",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Archive successful: {data['message']}")
            print(f"   Order: {data['order_name']}")
            print(f"   Reason: {data['archive_reason']}")
            print(f"   Archived at: {data['archived_at']}")
        else:
            print(f"   ❌ Archive failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        # Test that the analysis is no longer in active analyses
        print(f"\\n2. Verifying analysis is removed from active analyses...")
        response = requests.get(f"{base_url}/fraud-detection/analyses", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            active_analyses = data.get('analyses', [])
            found_in_active = False
            for analysis in active_analyses:
                if analysis['id'] == active_analysis.id:
                    found_in_active = True
                    break
            
            if not found_in_active:
                print(f"   ✅ Analysis correctly removed from active analyses")
            else:
                print(f"   ❌ Analysis still found in active analyses")
                return False
        else:
            print(f"   ❌ Failed to get analyses: {response.status_code}")
            return False
        
        # Test archived analyses endpoint
        print(f"\\n3. Testing archived analyses endpoint...")
        response = requests.get(f"{base_url}/fraud-detection/archived-analyses", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            archived_analyses = data.get('data', [])
            found_archived = False
            
            for analysis in archived_analyses:
                if analysis['id'] == active_analysis.id:
                    found_archived = True
                    print(f"   ✅ Found archived analysis in archived endpoint")
                    print(f"   Order: {analysis['order_name']}")
                    print(f"   Archive reason: {analysis.get('archive_reason', 'N/A')}")
                    break
            
            if not found_archived:
                print(f"   ❌ Archived analysis not found in archived endpoint")
                return False
        else:
            print(f"   ❌ Failed to get archived analyses: {response.status_code}")
            return False
        
        print("\\n✅ All manual archive tests passed!")
        return True
        
    except Exception as e:
        print(f"\\n❌ Error during testing: {str(e)}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = test_manual_archive()
    sys.exit(0 if success else 1)