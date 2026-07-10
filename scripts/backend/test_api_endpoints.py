#!/usr/bin/env python3
"""
Test script for the fraud analysis archival API endpoints.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import requests
import json
from database import SessionLocal
from models import User
from auth import create_access_token

def test_api_endpoints():
    """Test the fraud analysis archival API endpoints."""
    print("Testing fraud analysis archival API endpoints...")
    
    # Get database session
    db = SessionLocal()
    
    try:
        # Get a test user and create a token
        test_user = db.query(User).first()
        if not test_user:
            print("   ❌ No users found in database")
            return False
        
        token = create_access_token(data={"sub": test_user.email})
        headers = {"Authorization": f"Bearer {token}"}
        
        base_url = "http://localhost:8000"
        
        # Test 1: Get regular fraud analyses
        print("\n1. Testing regular fraud analyses endpoint...")
        response = requests.get(f"{base_url}/fraud-detection/analyses", headers=headers)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Regular endpoint working. Found {len(data.get('analyses', []))} analyses")
        else:
            print(f"   ❌ Regular endpoint failed: {response.status_code}")
            return False
        
        # Test 2: Get archived fraud analyses
        print("\n2. Testing archived fraud analyses endpoint...")
        response = requests.get(f"{base_url}/fraud-detection/archived-analyses", headers=headers)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Archived endpoint working. Found {data.get('total', 0)} archived analyses")
        else:
            print(f"   ❌ Archived endpoint failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        # Test 3: Test archived endpoint with filters
        print("\n3. Testing archived endpoint with filters...")
        response = requests.get(f"{base_url}/fraud-detection/archived-analyses?limit=10&skip=0", headers=headers)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Archived endpoint with filters working. Total: {data.get('total', 0)}")
        else:
            print(f"   ❌ Archived endpoint with filters failed: {response.status_code}")
            return False
        
        # Test 4: Test regular endpoint with include_archived parameter
        print("\n4. Testing regular endpoint with include_archived parameter...")
        response = requests.get(f"{base_url}/fraud-detection/analyses?include_archived=true", headers=headers)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Regular endpoint with include_archived working. Found {len(data.get('analyses', []))} analyses")
        else:
            print(f"   ❌ Regular endpoint with include_archived failed: {response.status_code}")
            return False
        
        print("\n✅ All API endpoint tests passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error during API testing: {str(e)}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = test_api_endpoints()
    sys.exit(0 if success else 1)