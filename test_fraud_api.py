#!/usr/bin/env python3
"""
Quick test script to verify fraud detection API is working with delivery analytics
"""
import requests
import json

# Configuration
API_BASE = "http://localhost:8000"
TEST_ORDER_NAME = "PW110446"  # Replace with a real order from your store
TEST_STORE_ID = 2  # Replace with your store ID

def test_fraud_detection_api():
    """Test the fraud detection API endpoints"""
    
    print("🧪 Testing Fraud Detection API with Enhanced Delivery Tracking")
    print("=" * 65)
    
    # You'll need to get an auth token first
    # For testing, you can get it from your browser's network tab or login endpoint
    
    auth_token = input("Enter your JWT token (from browser): ").strip()
    
    if not auth_token:
        print("❌ No auth token provided. Get it from your browser's network tab.")
        return
    
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    
    # Test 1: Analyze order for fraud
    print(f"\n1️⃣ Testing fraud analysis for order: {TEST_ORDER_NAME}")
    print("-" * 50)
    
    try:
        url = f"{API_BASE}/fraud-detection/analyze/{TEST_STORE_ID}?order_name={TEST_ORDER_NAME}"
        print(f"Making request to: {url}")
        
        response = requests.post(url, headers=headers)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Fraud analysis successful!")
            print(f"   Analysis ID: {result.get('analysis_id')}")
            print(f"   Status: {result.get('status')}")
            print(f"   Order: {result.get('order_name')}")
            print(f"   Timestamp: {result.get('analyzed_at')}")
            
            analysis_id = result.get('analysis_id')
            
            # Test 2: Get detailed analysis
            if analysis_id:
                print(f"\n2️⃣ Getting detailed analysis for ID: {analysis_id}")
                print("-" * 50)
                
                detail_url = f"{API_BASE}/fraud-detection/analysis/{analysis_id}"
                detail_response = requests.get(detail_url, headers=headers)
                
                if detail_response.status_code == 200:
                    detail_result = detail_response.json()
                    analysis = detail_result.get('analysis', {})
                    
                    print("✅ Detailed analysis retrieved!")
                    print(f"   Order: {analysis.get('order_name')}")
                    print(f"   First-time Customer: {analysis.get('is_first_time_customer')}")
                    print(f"   Order Total: ${analysis.get('current_order_total')}")
                    print(f"   Previous Delivery Status: {analysis.get('previous_order_delivery_status')}")
                    print(f"   Current Delivery Status: {analysis.get('current_order_delivery_status')}")
                    print(f"   Shopify Risk Level: {analysis.get('shopify_fraud_risk_level')}")
                    
                    # Check if delivery analytics is present
                    if 'delivery_analytics' in detail_result:
                        print(f"   📊 Delivery Analytics: ✅ Available")
                        delivery_analytics = detail_result.get('delivery_analytics', {})
                        if delivery_analytics:
                            history = delivery_analytics.get('customer_delivery_history', {})
                            print(f"      - Total Orders: {history.get('total_orders', 'N/A')}")
                            print(f"      - Delivered Orders: {history.get('delivered_orders', 'N/A')}")
                            print(f"      - Success Rate: {history.get('delivery_success_rate', 0):.1%}")
                    else:
                        print(f"   📊 Delivery Analytics: ❌ Not available")
                        
                else:
                    print(f"❌ Failed to get detailed analysis: {detail_response.status_code}")
                    print(f"   Error: {detail_response.text}")
            
        else:
            print(f"❌ Fraud analysis failed: {response.status_code}")
            print(f"   Error: {response.text}")
            
    except Exception as e:
        print(f"❌ Request failed: {str(e)}")
    
    # Test 3: List all analyses
    print(f"\n3️⃣ Testing analysis list endpoint")
    print("-" * 40)
    
    try:
        list_url = f"{API_BASE}/fraud-detection/analyses?per_page=5"
        list_response = requests.get(list_url, headers=headers)
        
        if list_response.status_code == 200:
            list_result = list_response.json()
            analyses = list_result.get('analyses', [])
            
            print(f"✅ Retrieved {len(analyses)} analyses")
            print(f"   Total available: {list_result.get('total', 0)}")
            
            for i, analysis in enumerate(analyses[:3]):  # Show first 3
                print(f"   {i+1}. Order {analysis.get('order_name')} - {analysis.get('analysis_timestamp', 'N/A')}")
                
        else:
            print(f"❌ Failed to list analyses: {list_response.status_code}")
            print(f"   Error: {list_response.text}")
            
    except Exception as e:
        print(f"❌ List request failed: {str(e)}")
    
    print(f"\n🎉 Fraud Detection API Test Complete!")
    print("=" * 65)

if __name__ == "__main__":
    test_fraud_detection_api()