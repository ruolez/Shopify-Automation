#!/usr/bin/env python3
"""
Test the reconcile endpoint directly via API
"""
import requests
import json
import sys
import os
from datetime import datetime

# API configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

def test_reconcile_endpoint(token: str):
    """Test the reconcile endpoint"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print("Testing fraud detection reconcile endpoint...")
    print(f"API URL: {API_BASE_URL}/fraud-detection/archive-fulfilled-cancelled")
    print(f"Time: {datetime.now()}")
    print("-" * 50)
    
    try:
        # Call the reconcile endpoint
        response = requests.post(
            f"{API_BASE_URL}/fraud-detection/archive-fulfilled-cancelled",
            headers=headers
        )
        
        print(f"Response Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            print("\nResponse Data:")
            print(json.dumps(data, indent=2))
            
            # Summarize results
            print("\n=== SUMMARY ===")
            print(f"Message: {data.get('message', 'N/A')}")
            print(f"Checked: {data.get('checked_count', 0)}")
            print(f"Archived: {data.get('archived_count', 0)}")
            print(f"Remaining: {data.get('total_remaining', 0)}")
            
            if data.get('archived_orders'):
                print("\nArchived Orders:")
                for order in data['archived_orders']:
                    print(f"  - {order['order_name']} ({order['archive_reason']})")
        else:
            print(f"\nError Response:")
            print(response.text)
            
    except Exception as e:
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()

def get_fraud_analyses(token: str):
    """Get current fraud analyses to see what might be archived"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print("\nFetching current fraud analyses...")
    
    try:
        response = requests.get(
            f"{API_BASE_URL}/fraud-detection/analyses?limit=10",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"Total analyses: {data.get('total', 0)}")
            
            if data.get('analyses'):
                print("\nFirst few analyses:")
                for analysis in data['analyses'][:5]:
                    print(f"  - Order: {analysis['order_name']}")
                    print(f"    Shopify Risk: {analysis.get('shopify_fraud_risk_level', 'N/A')}")
                    print(f"    Customer: {analysis.get('customer_name', 'N/A')}")
                    print(f"    Created: {analysis.get('analysis_timestamp', 'N/A')}")
        else:
            print(f"Error fetching analyses: {response.status_code}")
            
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_reconcile_endpoint.py <auth_token>")
        print("\nYou can get your auth token by:")
        print("1. Login to the frontend")
        print("2. Open browser developer tools")
        print("3. Go to Application/Storage -> Local Storage")
        print("4. Copy the 'token' value")
        sys.exit(1)
    
    token = sys.argv[1]
    
    # First show current analyses
    get_fraud_analyses(token)
    
    print("\n" + "=" * 50)
    
    # Then test reconcile
    test_reconcile_endpoint(token)