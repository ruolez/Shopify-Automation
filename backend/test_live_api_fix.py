#!/usr/bin/env python3
"""
Test the live API to verify the fix is working after restart
"""
import sys
import os
import requests
import json
import time

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

def test_live_api_fix():
    """Test the live API to see if the fix is working"""
    
    print("🔍 TESTING LIVE API AFTER RESTART")
    print("=" * 40)
    
    # Wait a moment for services to be ready
    print("⏳ Waiting for services to start...")
    time.sleep(5)
    
    base_url = "http://localhost:8000"
    
    try:
        # First, clear any existing analysis for PW15996
        print("1️⃣ Clearing existing analysis...")
        from database import get_db
        from models import FraudAnalysis
        
        db = next(get_db())
        existing = db.query(FraudAnalysis).filter(FraudAnalysis.order_name == 'PW15996').all()
        for analysis in existing:
            db.delete(analysis)
        db.commit()
        print(f"🗑️  Deleted {len(existing)} existing analyses")
        
        # Try to login as the correct user
        login_data = {
            "email": "alexr@tobaccogeneral.com",
            "password": "shopify123"
        }
        
        print("2️⃣ Logging in...")
        login_response = requests.post(f"{base_url}/auth/login", json=login_data, timeout=10)
        
        if login_response.status_code == 200:
            token = login_response.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            print("✅ Login successful")
        else:
            print(f"❌ Login failed: {login_response.status_code}")
            return
        
        # Create a new analysis for PW15996
        print("3️⃣ Creating fresh analysis for PW15996...")
        analysis_response = requests.post(
            f"{base_url}/fraud-detection/analyze/2?order_name=PW15996",
            headers=headers,
            timeout=30
        )
        
        if analysis_response.status_code == 200:
            analysis_data = analysis_response.json()
            analysis_id = analysis_data["analysis_id"]
            print(f"✅ Analysis created with ID: {analysis_id}")
            
            # Get the detailed analysis (this is what the frontend calls)
            print("4️⃣ Fetching analysis details...")
            detail_response = requests.get(
                f"{base_url}/fraud-detection/analysis/{analysis_id}",
                headers=headers,
                timeout=10
            )
            
            if detail_response.status_code == 200:
                detail_data = detail_response.json()
                analysis = detail_data["analysis"]
                
                print(f"\n📊 LIVE API RESPONSE:")
                print(f"   Analysis ID: {analysis['id']}")
                print(f"   Order: {analysis['order_name']}")
                print(f"   Previous Delivery Status: '{analysis['previous_order_delivery_status']}'")
                print(f"   Current Delivery Status: '{analysis['current_order_delivery_status']}'")
                
                # Check if the fix worked
                prev_status = analysis['previous_order_delivery_status']
                current_status = analysis['current_order_delivery_status']
                
                if prev_status and 'april' in prev_status.lower():
                    print(f"\n✅ SUCCESS: Fix is working! Previous order shows April delivery")
                elif prev_status and 'august' in prev_status.lower():
                    print(f"\n❌ FIX NOT APPLIED: Still showing August (current order) as previous")
                elif prev_status is None or prev_status == "":
                    print(f"\n⚠️  Previous delivery status is empty/null")
                else:
                    print(f"\n🤔 Unexpected previous status: '{prev_status}'")
                
                if current_status and 'august' in current_status.lower():
                    print(f"✅ Current order status correct: August delivery")
                
                # Show the exact JSON for debugging
                print(f"\n📄 EXACT FRONTEND JSON RESPONSE:")
                relevant_data = {
                    "analysis": {
                        "id": analysis['id'],
                        "order_name": analysis['order_name'],
                        "previous_order_delivery_status": analysis['previous_order_delivery_status'],
                        "current_order_delivery_status": analysis['current_order_delivery_status']
                    }
                }
                print(json.dumps(relevant_data, indent=2))
                
            else:
                print(f"❌ Failed to get analysis details: {detail_response.status_code}")
                
        else:
            print(f"❌ Failed to create analysis: {analysis_response.status_code}")
            print(f"Response: {analysis_response.text}")
            
    except Exception as e:
        print(f"❌ Error testing live API: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎯 FRONTEND TESTING INSTRUCTIONS:")
    print("=" * 40)
    print("1. Go to: http://localhost:3000/fraud-detection")
    print("2. Clear browser cache (Ctrl+F5 or Cmd+Shift+R)")
    print("3. Select Store: Primewholesale.com")
    print("4. Order Name: PW15996")
    print("5. Click: Analyze Order")
    print("6. Check: Previous Order Delivery Status")
    print("   Should show: 'Delivered on April 8th 2024' (NOT N/A)")
    
    print(f"\n🎉 Live API Test Complete!")
    print("=" * 30)

if __name__ == "__main__":
    test_live_api_fix()