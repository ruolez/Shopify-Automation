#!/usr/bin/env python3
"""
Test the actual API endpoint to see what response is returned
"""
import sys
import os
import asyncio
import requests
import json
from datetime import datetime

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

def test_api_endpoint():
    """Test the fraud analysis API endpoint directly"""
    
    print("🌐 TESTING FRAUD ANALYSIS API ENDPOINT")
    print("=" * 50)
    
    # First, create a test user if needed and get a valid token
    base_url = "http://localhost:8000"
    
    # Try to login with a test user (we'll use the user from our tests)
    login_data = {
        "email": "user@example.com",
        "password": "testpassword"
    }
    
    try:
        print("1️⃣ Attempting to login...")
        login_response = requests.post(f"{base_url}/auth/login", json=login_data)
        
        if login_response.status_code == 200:
            token = login_response.json()["access_token"]
            print(f"✅ Login successful")
        else:
            print(f"❌ Login failed: {login_response.status_code} - {login_response.text}")
            print("Creating a test user...")
            
            # Try to register the user
            register_data = {
                "email": "user@example.com",
                "password": "testpassword",
                "full_name": "Test User"
            }
            
            register_response = requests.post(f"{base_url}/auth/register", json=register_data)
            if register_response.status_code == 200:
                token = register_response.json()["access_token"]
                print("✅ User registered and logged in")
            else:
                print(f"❌ Registration failed: {register_response.status_code} - {register_response.text}")
                return
        
        headers = {"Authorization": f"Bearer {token}"}
        
        # Test fraud analysis endpoint directly
        print(f"\n2️⃣ Testing fraud analysis endpoint for analysis ID 2...")
        analysis_response = requests.get(f"{base_url}/fraud-detection/analysis/2", headers=headers)
        
        if analysis_response.status_code == 200:
            data = analysis_response.json()
            analysis = data["analysis"]
            
            print("✅ API Response received successfully!")
            print(f"\n📊 Analysis Data:")
            print(f"   Order Name: {analysis['order_name']}")
            print(f"   Store ID: {analysis['store_id']}")
            print(f"   User ID: {analysis['user_id']}")
            print(f"   Previous Delivery Status: \"{analysis['previous_order_delivery_status']}\"")
            print(f"   Current Delivery Status: \"{analysis['current_order_delivery_status']}\"")
            print(f"   First Time Customer: {analysis['is_first_time_customer']}")
            print(f"   Previous Order Total: ${analysis['previous_order_total']}")
            
            # Check if the August 5th data is there
            prev_status = analysis['previous_order_delivery_status']
            if prev_status and 'august' in prev_status.lower() and '2024' in prev_status:
                print("🎯 SUCCESS: August 5th 2024 delivery data found in API response!")
            elif prev_status:
                print(f"⚠️  Previous delivery status found but not August 2024: '{prev_status}'")
            else:
                print(f"❌ Previous delivery status is null/empty: {prev_status}")
                
            # Show the full JSON for debugging
            print(f"\n📄 Full API Response:")
            print("=" * 30)
            print(json.dumps(data, indent=2))
            
        elif analysis_response.status_code == 404:
            print("❌ Analysis ID 2 not found - this user may not have access to it")
            print("Let's check what analyses this user has...")
            
            analyses_response = requests.get(f"{base_url}/fraud-detection/analyses", headers=headers)
            if analyses_response.status_code == 200:
                analyses = analyses_response.json()["analyses"]
                print(f"User has {len(analyses)} analyses:")
                for analysis in analyses:
                    print(f"  ID {analysis['id']}: {analysis['order_name']} - {analysis['previous_order_delivery_status']}")
            else:
                print(f"❌ Failed to get analyses: {analyses_response.status_code}")
        else:
            print(f"❌ API Error: {analysis_response.status_code}")
            print(f"Response: {analysis_response.text}")
            
        # Test creating a new analysis for PW15996 to see live data
        print(f"\n3️⃣ Testing live analysis creation for PW15996...")
        
        # First, check available stores
        stores_response = requests.get(f"{base_url}/stores", headers=headers)
        if stores_response.status_code == 200:
            stores = stores_response.json()
            print(f"User has {len(stores)} stores:")
            for store in stores:
                print(f"  Store ID {store['id']}: {store['shop_name']}")
                
            if stores:
                # Use the first store
                store_id = stores[0]['id']
                print(f"Using store ID {store_id} for analysis...")
                
                analysis_create_response = requests.post(
                    f"{base_url}/fraud-detection/analyze/{store_id}?order_name=PW15996", 
                    headers=headers
                )
                
                if analysis_create_response.status_code == 200:
                    create_data = analysis_create_response.json()
                    analysis_id = create_data['analysis_id']
                    print(f"✅ Analysis created with ID: {analysis_id}")
                    
                    # Get the detailed analysis
                    detail_response = requests.get(f"{base_url}/fraud-detection/analysis/{analysis_id}", headers=headers)
                    if detail_response.status_code == 200:
                        detail_data = detail_response.json()
                        detail_analysis = detail_data["analysis"]
                        
                        print(f"\n🔍 Fresh Analysis Results:")
                        print(f"   Previous Delivery Status: \"{detail_analysis['previous_order_delivery_status']}\"")
                        print(f"   Current Delivery Status: \"{detail_analysis['current_order_delivery_status']}\"")
                        
                        if detail_analysis['previous_order_delivery_status'] and 'august' in detail_analysis['previous_order_delivery_status'].lower():
                            print("🎯 SUCCESS: Fresh analysis shows August 2024 delivery!")
                        else:
                            print(f"❌ Fresh analysis still not showing August data: '{detail_analysis['previous_order_delivery_status']}'")
                else:
                    print(f"❌ Failed to create analysis: {analysis_create_response.status_code} - {analysis_create_response.text}")
            else:
                print("❌ User has no stores configured")
        else:
            print(f"❌ Failed to get stores: {stores_response.status_code}")
            
    except Exception as e:
        print(f"❌ Error testing API: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎉 API Testing Complete!")
    print("=" * 30)

if __name__ == "__main__":
    test_api_endpoint()