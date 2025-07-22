#!/usr/bin/env python3
"""
Simple test to focus on delivery date extraction
"""
import asyncio
import sys
import os
import json
from datetime import datetime

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

from fraud_service import FraudAnalysisService, format_ordinal_date
from shopify_client import ShopifyClient
from database import get_db
from models import ShopifyStore, User

async def simple_delivery_test():
    """Simple test focused on delivery date extraction"""
    
    print("🧪 SIMPLE DELIVERY DATE TEST")
    print("=" * 40)
    
    # Test the date formatting function first
    print("1️⃣ Testing date formatting function...")
    test_date = datetime(2024, 8, 5, 12, 30, 0)
    formatted = format_ordinal_date(test_date)
    print(f"August 5, 2024 formats to: '{formatted}'")
    
    # Test actual API call
    db = next(get_db())
    store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
    user = db.query(User).filter(User.id == 4).first()
    
    if not store or not user:
        print("❌ No store or user found")
        return
    
    client = ShopifyClient(
        shop_domain=store.shop_domain,
        access_token=store.access_token
    )
    
    fraud_service = FraudAnalysisService(db, store, user)
    
    order_name = input("Enter order name to test: ").strip()
    if not order_name:
        return
    
    print(f"\n2️⃣ Testing with order: {order_name}")
    
    # Get order data
    order_data = await client.get_order_fraud_data(order_name)
    if not order_data:
        print("❌ No order data")
        return
    
    print("✅ Order data retrieved")
    
    # Test current order delivery status
    current_status = fraud_service._extract_delivery_tracking_status(order_data)
    print(f"Current order delivery status: '{current_status}'")
    
    # Test previous order methods
    prev_bool = fraud_service._get_previous_order_delivery_status(order_data)
    print(f"Previous order delivered (boolean): {prev_bool}")
    
    prev_status, prev_total = fraud_service._get_previous_order_data(order_data)
    print(f"Previous order delivery status: '{prev_status}'")
    print(f"Previous order total: ${prev_total}")
    
    # Test comprehensive analytics
    analytics = fraud_service._get_comprehensive_delivery_analytics(order_data)
    print(f"Analytics previous status: '{analytics.get('previous_order_delivery_status')}'")
    
    # Show raw fulfillment data for debugging
    customer = order_data.get('customer', {})
    if customer:
        orders = customer.get('orders', {}).get('edges', [])
        print(f"\n3️⃣ Raw Customer Order Data:")
        print(f"Total orders in history: {len(orders)}")
        
        if len(orders) >= 2:
            prev_order = orders[1]['node']
            print(f"Previous order: {prev_order.get('name')}")
            print(f"Display fulfillment status: {prev_order.get('displayFulfillmentStatus')}")
            
            fulfillments = prev_order.get('fulfillments', [])
            print(f"Fulfillments: {len(fulfillments)}")
            
            for i, fulfillment in enumerate(fulfillments):
                delivered_at = fulfillment.get('deliveredAt')
                display_status = fulfillment.get('displayStatus')
                status = fulfillment.get('status')
                
                print(f"  Fulfillment {i+1}:")
                print(f"    deliveredAt: {delivered_at}")
                print(f"    displayStatus: {display_status}")
                print(f"    status: {status}")
                
                if delivered_at:
                    try:
                        parsed_date = datetime.fromisoformat(delivered_at.replace('Z', '+00:00'))
                        formatted_date = format_ordinal_date(parsed_date)
                        print(f"    📅 Parsed as: {formatted_date}")
                        
                        if parsed_date.year == 2024 and parsed_date.month == 8 and parsed_date.day == 5:
                            print("    ✅ THIS IS AUGUST 5TH, 2024!")
                            
                    except Exception as e:
                        print(f"    ❌ Date parsing error: {e}")
                
                # Check events
                events = fulfillment.get('events', {}).get('edges', [])
                print(f"    Events: {len(events)}")
                
                for j, event_edge in enumerate(events[:3]):
                    event = event_edge['node']
                    event_status = event.get('status')
                    happened_at = event.get('happenedAt')
                    print(f"      Event {j+1}: {event_status} at {happened_at}")

if __name__ == "__main__":
    asyncio.run(simple_delivery_test())