#!/usr/bin/env python3
"""
Test the manual reconcile endpoint
"""
import requests
import sys
import json
from datetime import datetime

def test_manual_reconcile(token: str):
    """Test the manual reconcile endpoint"""
    
    api_url = "http://localhost:8000"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print("=" * 50)
    print("Testing Manual Reconcile Endpoint")
    print("=" * 50)
    print(f"Time: {datetime.now()}")
    print(f"API URL: {api_url}/fraud-detection/archive-fulfilled-cancelled")
    
    try:
        # Call the reconcile endpoint
        response = requests.post(
            f"{api_url}/fraud-detection/archive-fulfilled-cancelled",
            headers=headers
        )
        
        print(f"\nResponse Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("\n✓ Reconcile completed successfully!")
            print(f"Message: {data.get('message')}")
            print(f"Checked: {data.get('checked_count', 0)} orders")
            print(f"Archived: {data.get('archived_count', 0)} orders")
            print(f"Remaining: {data.get('total_remaining', 0)} orders")
            
            if data.get('archived_orders'):
                print("\nArchived Orders:")
                for order in data['archived_orders'][:10]:  # Show first 10
                    print(f"  - {order['order_name']}: {order['archive_reason']}")
                if len(data['archived_orders']) > 10:
                    print(f"  ... and {len(data['archived_orders']) - 10} more")
        else:
            print(f"\n✗ Error: {response.status_code}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"\n✗ Error calling API: {str(e)}")
        return False
    
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_manual_reconcile.py <auth_token>")
        print("\nYou can get your auth token by:")
        print("1. Login to the frontend")
        print("2. Open browser developer tools")
        print("3. Go to Application/Storage -> Local Storage")
        print("4. Find the 'token' value")
        sys.exit(1)
    
    token = sys.argv[1]
    test_manual_reconcile(token)