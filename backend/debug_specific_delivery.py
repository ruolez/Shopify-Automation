#!/usr/bin/env python3
"""
Debug script specifically for the August 5th 2024 delivery issue
"""
import sys
import os
from datetime import datetime

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

from fraud_service import format_ordinal_date

def test_date_formatting():
    """Test the date formatting with the specific August 5th 2024 data"""
    
    print("🧪 DEBUGGING AUGUST 5TH 2024 DELIVERY DATE FORMATTING")
    print("=" * 60)
    
    # Test the exact timestamp from your raw data
    delivered_at_raw = "2024-08-05T20:13:00Z"
    
    print(f"Raw deliveredAt from Shopify: {delivered_at_raw}")
    
    try:
        # Parse the date exactly as our code does
        delivery_datetime = datetime.fromisoformat(delivered_at_raw.replace('Z', '+00:00'))
        print(f"Parsed datetime: {delivery_datetime}")
        print(f"Year: {delivery_datetime.year}")
        print(f"Month: {delivery_datetime.month}")
        print(f"Day: {delivery_datetime.day}")
        print(f"Hour: {delivery_datetime.hour}")
        
        # Format with our ordinal function
        formatted_date = format_ordinal_date(delivery_datetime)
        print(f"Formatted with format_ordinal_date(): '{formatted_date}'")
        
        # Create the full status string
        status_text = f"Delivered on {formatted_date}"
        print(f"Full status text: '{status_text}'")
        
        # Test if this would pass our filtering logic
        contains_on = ' on ' in status_text.lower()
        contains_since = ' since ' in status_text.lower()
        
        print(f"Contains ' on ': {contains_on}")
        print(f"Contains ' since ': {contains_since}")
        print(f"Would pass old filter: {contains_on or contains_since}")
        
        # Test new filtering logic
        not_invalid = status_text.lower() not in ['unknown', 'unfulfilled', 'none', '']
        print(f"Would pass new filter: {not_invalid}")
        
        return status_text
        
    except Exception as e:
        print(f"❌ Error parsing date: {e}")
        return None

def test_mock_fulfillment_data():
    """Test with the exact fulfillment structure from your raw data"""
    
    print(f"\n📦 TESTING WITH MOCK FULFILLMENT DATA")
    print("=" * 50)
    
    # Mock fulfillment data based on your raw response
    mock_fulfillment_data = {
        "fulfillments": [
            {
                "id": "gid://shopify/Fulfillment/5159562412334",
                "status": "SUCCESS",
                "displayStatus": "FULFILLED",
                "deliveredAt": None,  # First fulfillment - no delivery
                "inTransitAt": None,
                "createdAt": "2024-08-02T22:21:03Z",
                "trackingInfo": [],
                "events": {"edges": []}
            },
            {
                "id": "gid://shopify/Fulfillment/5159562346798",
                "status": "SUCCESS", 
                "displayStatus": "DELIVERED",
                "deliveredAt": "2024-08-05T20:13:00Z",  # THIS IS THE KEY DATA
                "inTransitAt": "2024-08-04T02:07:00Z",
                "createdAt": "2024-08-02T22:21:02Z",
                "trackingInfo": [
                    {
                        "company": "usps",
                        "number": "9405511206204213246775",
                        "url": "https://tools.usps.com/go/TrackConfirmAction_input?qtc_tLabels1=9405511206204213246775"
                    }
                ],
                "events": {
                    "edges": [
                        {
                            "node": {
                                "id": "gid://shopify/FulfillmentEvent/27749340217646",
                                "status": "DELIVERED",
                                "happenedAt": "2024-08-05T20:13:00Z",
                                "message": "DELIVERED FRONT DOOR/PORCH",
                                "estimatedDeliveryAt": "2024-08-07T23:59:59Z"
                            }
                        },
                        {
                            "node": {
                                "id": "gid://shopify/FulfillmentEvent/27747546562862", 
                                "status": "OUT_FOR_DELIVERY",
                                "happenedAt": "2024-08-05T11:59:00Z",
                                "message": "OUT FOR DELIVERY",
                                "estimatedDeliveryAt": "2024-08-07T23:59:59Z"
                            }
                        }
                    ]
                }
            }
        ]
    }
    
    # Import the fraud service and test our extraction logic
    try:
        from fraud_service import FraudAnalysisService
        from database import get_db
        from models import ShopifyStore, User
        
        # Create a mock fraud service (we won't actually save anything)
        db = next(get_db())
        store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
        user = db.query(User).filter(User.id == 4).first()
        
        if store and user:
            fraud_service = FraudAnalysisService(db, store, user)
            
            print(f"Testing _extract_delivery_tracking_status() with mock data...")
            result = fraud_service._extract_delivery_tracking_status(mock_fulfillment_data)
            print(f"Result: '{result}'")
            
            if result and 'august' in result.lower() and '2024' in result:
                print(f"✅ SUCCESS: August 2024 delivery detected!")
            elif result and 'delivered' in result.lower():
                print(f"⚠️  PARTIAL: Delivery detected but no specific date")
            else:
                print(f"❌ FAILED: August 2024 delivery NOT detected")
                
        else:
            print("❌ Could not create fraud service for testing")
            
    except Exception as e:
        print(f"❌ Error testing fraud service: {e}")

def test_manual_extraction():
    """Manually test the extraction logic step by step"""
    
    print(f"\n🔍 MANUAL STEP-BY-STEP EXTRACTION")
    print("=" * 45)
    
    delivered_at = "2024-08-05T20:13:00Z"
    
    print(f"1. Raw deliveredAt: {delivered_at}")
    
    try:
        # Step 1: Parse datetime
        delivery_datetime = datetime.fromisoformat(delivered_at.replace('Z', '+00:00'))
        print(f"2. Parsed datetime: {delivery_datetime}")
        
        # Step 2: Format ordinal date
        formatted_date = format_ordinal_date(delivery_datetime)
        print(f"3. Formatted date: '{formatted_date}'")
        
        # Step 3: Create status text
        status_text = f"Delivered on {formatted_date}"
        print(f"4. Status text: '{status_text}'")
        
        # Step 4: Check if this should be returned
        is_valid = status_text.lower() not in ['unknown', 'unfulfilled', 'none', '']
        print(f"5. Is valid status: {is_valid}")
        
        if is_valid:
            print(f"✅ This SHOULD be returned as the delivery status!")
        else:
            print(f"❌ This would be filtered out")
            
        return status_text
        
    except Exception as e:
        print(f"❌ Manual extraction failed: {e}")
        return None

if __name__ == "__main__":
    print("🔍 DEBUGGING AUGUST 5TH 2024 DELIVERY EXTRACTION")
    print("=" * 60)
    
    # Test 1: Date formatting
    status_from_date = test_date_formatting()
    
    # Test 2: Mock fulfillment data 
    test_mock_fulfillment_data()
    
    # Test 3: Manual extraction
    manual_status = test_manual_extraction()
    
    print(f"\n🎯 SUMMARY")
    print("=" * 20)
    print(f"Date formatting result: '{status_from_date}'")
    print(f"Manual extraction result: '{manual_status}'")
    
    if status_from_date and 'august' in status_from_date.lower():
        print(f"✅ Date formatting is working correctly")
    else:
        print(f"❌ Issue with date formatting")
        
    print(f"\nThe delivery status should be showing as something like:")
    print(f"'{status_from_date}' for August 5th, 2024 delivery")