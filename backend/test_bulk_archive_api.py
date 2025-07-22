#!/usr/bin/env python3
"""Test script to diagnose bulk archive API issue"""
import requests
import json
import sys

# Configuration
API_BASE_URL = "http://localhost:8000"
TEST_USER_EMAIL = "ruolez@gmail.com"  # Replace with your test user email
TEST_USER_PASSWORD = "test"  # Replace with your test user password

def main():
    # Step 1: Login to get JWT token
    print("1. Logging in...")
    login_response = requests.post(
        f"{API_BASE_URL}/auth/login",
        json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        }
    )
    
    if login_response.status_code != 200:
        print(f"Login failed: {login_response.status_code}")
        print(f"Response: {login_response.text}")
        sys.exit(1)
    
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Login successful!")
    
    # Step 2: Call bulk archive endpoint
    print("\n2. Calling bulk archive endpoint...")
    archive_response = requests.post(
        f"{API_BASE_URL}/fraud-detection/archive-fulfilled-cancelled",
        headers=headers
    )
    
    print(f"Status Code: {archive_response.status_code}")
    print(f"Response: {archive_response.text}")
    
    if archive_response.status_code == 200:
        data = archive_response.json()
        print(f"\nSuccess! Archived {data['archived_count']} out of {data['checked_count']} analyses")
        if data['archived_orders']:
            print("\nArchived orders:")
            for order in data['archived_orders']:
                print(f"  - {order['order_name']}: {order['archive_reason']}")
    else:
        print(f"\nError: {archive_response.status_code}")
        try:
            error_data = archive_response.json()
            print(f"Error detail: {error_data.get('detail', 'No detail provided')}")
        except:
            print(f"Raw error: {archive_response.text}")

if __name__ == "__main__":
    main()