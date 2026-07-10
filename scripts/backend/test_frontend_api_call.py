#!/usr/bin/env python3
"""
Test the exact API call that the frontend makes for PW110472
"""
import sys
import os
import requests
import json

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

def test_frontend_api_call():
    """Test the exact API call sequence that the frontend makes"""
    
    print("🔍 TESTING EXACT FRONTEND API CALLS FOR PW110472")
    print("=" * 60)
    
    base_url = "http://localhost:8000"
    
    try:
        # Step 1: Login (same as frontend)
        login_data = {
            "email": "alexr@tobaccogeneral.com",
            "password": "shopify123"
        }
        
        print("1️⃣ Frontend Login...")
        login_response = requests.post(f"{base_url}/auth/login", json=login_data, timeout=10)
        
        if login_response.status_code != 200:
            print(f"❌ Login failed: {login_response.status_code}")
            return
            
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("✅ Login successful")
        
        # Step 2: Clear any existing analysis for PW110472
        print("2️⃣ Clearing existing analysis...")
        from database import get_db
        from models import FraudAnalysis
        
        db = next(get_db())
        existing = db.query(FraudAnalysis).filter(FraudAnalysis.order_name == 'PW110472').all()
        for analysis in existing:
            db.delete(analysis)
        db.commit()
        print(f"🗑️  Deleted {len(existing)} existing analyses")
        
        # Step 3: Create analysis (same API call as frontend button)
        print("3️⃣ Frontend Analysis Creation...")
        store_id = 2  # Primewholesale.com
        order_name = "PW110472"
        
        create_response = requests.post(
            f"{base_url}/fraud-detection/analyze/{store_id}?order_name={order_name}",
            headers=headers,
            timeout=30
        )
        
        if create_response.status_code != 200:
            print(f"❌ Analysis creation failed: {create_response.status_code}")
            print(f"Response: {create_response.text}")
            return
            
        create_data = create_response.json()
        analysis_id = create_data["analysis_id"]
        print(f"✅ Analysis created with ID: {analysis_id}")
        
        # Step 4: Get analysis details (same API call as frontend)
        print("4️⃣ Frontend Analysis Fetch...")
        detail_response = requests.get(
            f"{base_url}/fraud-detection/analysis/{analysis_id}",
            headers=headers,
            timeout=10
        )
        
        if detail_response.status_code != 200:
            print(f"❌ Analysis fetch failed: {detail_response.status_code}")
            return
            
        detail_data = detail_response.json()
        analysis = detail_data["analysis"]
        
        print(f"\n📊 EXACT FRONTEND API RESPONSE:")
        print(f"   Analysis ID: {analysis['id']}")
        print(f"   Order Name: {analysis['order_name']}")
        print(f"   Previous Delivery Status: '{analysis['previous_order_delivery_status']}'")
        print(f"   Current Delivery Status: '{analysis['current_order_delivery_status']}'")
        
        # Check what the frontend would display
        prev_status = analysis['previous_order_delivery_status']
        
        # This is the exact logic from the frontend code
        display_value = prev_status if prev_status else "N/A"
        
        print(f"\n🎯 FRONTEND DISPLAY LOGIC:")
        print(f"   Raw API value: {repr(prev_status)}")
        print(f"   Frontend displays: '{display_value}'")
        
        if prev_status and 'august' in prev_status.lower():
            print(f"   ✅ SHOULD show: 'Delivered on August 5th 2024'")
        elif prev_status is None:
            print(f"   ❌ PROBLEM: API returned None - frontend shows 'N/A'")
        elif prev_status == "":
            print(f"   ❌ PROBLEM: API returned empty string - frontend shows 'N/A'")
        else:
            print(f"   ⚠️  Unexpected value: '{prev_status}'")
        
        # Show the complete JSON that frontend receives
        print(f"\n📄 COMPLETE FRONTEND JSON:")
        print("=" * 40)
        relevant_fields = {
            "analysis": {
                "id": analysis['id'],
                "order_name": analysis['order_name'],
                "previous_order_delivery_status": analysis['previous_order_delivery_status'],
                "current_order_delivery_status": analysis['current_order_delivery_status'],
                "is_first_time_customer": analysis['is_first_time_customer']
            },
            "store_name": detail_data['store_name']
        }
        print(json.dumps(relevant_fields, indent=2))
        
    except Exception as e:
        print(f"❌ Error testing frontend API: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎯 CONCLUSION:")
    print("=" * 20)
    print("If the API returns the correct data above but you still see N/A:")
    print("1. Hard refresh browser (Ctrl+F5 / Cmd+Shift+R)")
    print("2. Clear browser cache completely")
    print("3. Try incognito/private browsing mode")
    print("4. Check browser console for JavaScript errors")
    
    print(f"\n🎉 Frontend API Test Complete!")
    print("=" * 35)

if __name__ == "__main__":
    test_frontend_api_call()