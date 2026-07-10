#!/usr/bin/env python3
"""
Debug what the frontend API is actually receiving
"""
import sys
import os
import requests
import json
from datetime import datetime

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

def test_frontend_api_flow():
    """Test the exact API flow that the frontend uses"""
    
    print("🔍 DEBUGGING FRONTEND API FLOW")
    print("=" * 50)
    
    base_url = "http://localhost:8000"
    
    # Step 1: Try to analyze PW15996 with store ID 2 (which we know works)
    print("1️⃣ Testing fraud analysis creation...")
    
    # We need to get a valid auth token first. Let's create a simple user
    try:
        # Create a simple test user
        register_data = {
            "email": "frontendtest@example.com",
            "password": "testpass123",
            "full_name": "Frontend Test User"
        }
        
        # Try to register (will fail if exists, but that's ok)
        register_response = requests.post(f"{base_url}/auth/register", json=register_data)
        
        if register_response.status_code == 200:
            token = register_response.json()["access_token"]
            print("✅ New user registered")
        else:
            # Try to login instead
            login_data = {
                "email": "frontendtest@example.com", 
                "password": "testpass123"
            }
            login_response = requests.post(f"{base_url}/auth/login", json=login_data)
            
            if login_response.status_code == 200:
                token = login_response.json()["access_token"]
                print("✅ Existing user logged in")
            else:
                print(f"❌ Cannot get auth token: {login_response.status_code} - {login_response.text}")
                return
                
        headers = {"Authorization": f"Bearer {token}"}
        
        # Step 2: Create a store for this user first
        print("\n2️⃣ Setting up store for user...")
        
        # Check if user has stores
        stores_response = requests.get(f"{base_url}/stores", headers=headers)
        
        if stores_response.status_code == 200:
            stores = stores_response.json()
            if stores:
                store_id = stores[0]["id"]
                print(f"✅ Using existing store ID: {store_id}")
            else:
                print("❌ User has no stores - need to create one")
                # For this test, we'll manually assign store access in the database
                print("Creating store access via database...")
                
                # Add user to existing store via database
                import sys
                sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')
                from database import get_db
                from models import User, ShopifyStore
                
                db = next(get_db())
                user = db.query(User).filter(User.email == "frontendtest@example.com").first()
                
                if user:
                    # Create a test store for this user
                    test_store = ShopifyStore(
                        user_id=user.id,
                        shop_name="Test Store Frontend",
                        shop_domain="test-frontend.myshopify.com",
                        access_token="test_token_123",
                        is_active=True
                    )
                    db.add(test_store)
                    db.commit()
                    store_id = test_store.id
                    print(f"✅ Created test store ID: {store_id}")
                else:
                    print("❌ User not found in database")
                    return
        else:
            print(f"❌ Failed to get stores: {stores_response.status_code}")
            return
        
        # Step 3: Try to analyze order PW15996 
        print(f"\n3️⃣ Creating fraud analysis for PW15996...")
        
        analysis_create_response = requests.post(
            f"{base_url}/fraud-detection/analyze/{store_id}?order_name=PW15996", 
            headers=headers
        )
        
        if analysis_create_response.status_code == 200:
            create_data = analysis_create_response.json()
            analysis_id = create_data['analysis_id']
            print(f"✅ Analysis created with ID: {analysis_id}")
            
            # Step 4: Get the detailed analysis (this is what frontend does)
            print(f"\n4️⃣ Fetching analysis details (frontend API call)...")
            
            detail_response = requests.get(f"{base_url}/fraud-detection/analysis/{analysis_id}", headers=headers)
            
            if detail_response.status_code == 200:
                detail_data = detail_response.json()
                analysis = detail_data["analysis"]
                
                print(f"✅ Frontend API Response Received!")
                print(f"\n📊 FRONTEND DATA:")
                print(f"   Analysis ID: {analysis['id']}")
                print(f"   Order Name: {analysis['order_name']}")
                print(f"   Previous Delivery Status: '{analysis['previous_order_delivery_status']}'")
                print(f"   Current Delivery Status: '{analysis['current_order_delivery_status']}'")
                print(f"   Is First Time Customer: {analysis['is_first_time_customer']}")
                
                # Check specifically for the August 5th issue
                prev_status = analysis['previous_order_delivery_status']
                if prev_status is None:
                    print(f"\n❌ ISSUE FOUND: previous_order_delivery_status is None")
                elif prev_status == "":
                    print(f"\n❌ ISSUE FOUND: previous_order_delivery_status is empty string")
                elif 'august' in prev_status.lower() and '2024' in prev_status:
                    print(f"\n✅ SUCCESS: August 2024 delivery data found in frontend API!")
                else:
                    print(f"\n⚠️  Previous delivery status present but not August 2024: '{prev_status}'")
                
                # Show the exact JSON that frontend receives
                print(f"\n📄 EXACT FRONTEND JSON:")
                print("=" * 30)
                print(json.dumps(detail_data, indent=2))
                
            else:
                print(f"❌ Failed to get analysis details: {detail_response.status_code}")
                print(f"Response: {detail_response.text}")
                
        else:
            print(f"❌ Failed to create analysis: {analysis_create_response.status_code}")
            print(f"Response: {analysis_create_response.text}")
            
            # If this fails, it might be because this user doesn't have access to the Shopify store
            # Let's try to test with the existing analysis that we know works
            print(f"\n🔄 Trying to access existing analysis ID 2...")
            
            existing_response = requests.get(f"{base_url}/fraud-detection/analysis/2", headers=headers)
            
            if existing_response.status_code == 200:
                existing_data = existing_response.json()
                print(f"✅ Successfully accessed existing analysis!")
                analysis = existing_data["analysis"]
                print(f"   Previous Delivery Status: '{analysis['previous_order_delivery_status']}'")
            elif existing_response.status_code == 404:
                print(f"❌ Analysis ID 2 not found for this user (user permission issue)")
            else:
                print(f"❌ Error accessing existing analysis: {existing_response.status_code}")
                print(f"Response: {existing_response.text}")
            
    except Exception as e:
        print(f"❌ Error during frontend API test: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎉 Frontend API Debug Complete!")
    print("=" * 40)

if __name__ == "__main__":
    test_frontend_api_flow()