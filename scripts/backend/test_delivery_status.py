#!/usr/bin/env python3
"""
Test script to verify delivery status extraction works correctly
"""
import asyncio
import sys
import os
import json

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

from fraud_service import FraudAnalysisService
from shopify_client import ShopifyClient
from database import get_db
from models import ShopifyStore, User

async def test_delivery_status():
    """Test the delivery status extraction logic"""
    
    # Get a store and user from the database
    db = next(get_db())
    store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
    user = db.query(User).filter(User.id == 4).first()
    
    if not store or not user:
        print("No store or user found")
        return
    
    print(f"Testing with store: {store.shop_name}")
    
    # Create client and service
    client = ShopifyClient(
        shop_domain=store.shop_domain,
        access_token=store.access_token
    )
    
    fraud_service = FraudAnalysisService(db, store, user)
    
    # Get the order data
    order_name = "PW110446"
    print(f"Fetching fraud data for order: {order_name}")
    
    order_data = await client.get_order_fraud_data(order_name)
    
    if not order_data:
        print("No order data found")
        return
    
    # Extract current order delivery status
    current_delivery_status = fraud_service._extract_delivery_tracking_status(order_data)
    print(f"\nCurrent order delivery status: {current_delivery_status}")
    
    # Get previous order data 
    customer = order_data.get('customer', {})
    customer_orders = customer.get('orders', {}).get('edges', [])
    
    if len(customer_orders) >= 2:
        previous_order = customer_orders[1]['node']
        print(f"\nPrevious order: {previous_order.get('name')}")
        print(f"Previous order display status: {previous_order.get('displayFulfillmentStatus')}")
        
        # Test delivery status extraction for previous order
        fulfillments = previous_order.get('fulfillments', [])
        print(f"Previous order fulfillments count: {len(fulfillments)}")
        
        if fulfillments:
            previous_order_mock = {
                'fulfillments': fulfillments
            }
            prev_delivery_status = fraud_service._extract_delivery_tracking_status(previous_order_mock)
            print(f"Extracted previous order delivery status: {prev_delivery_status}")
            
            # Show the fulfillment details
            for i, fulfillment in enumerate(fulfillments):
                print(f"\n  Fulfillment {i+1}:")
                print(f"    Status: {fulfillment.get('status')}")
                print(f"    Display Status: {fulfillment.get('displayStatus')}")
                print(f"    Delivered At: {fulfillment.get('deliveredAt')}")
                
                events = fulfillment.get('events', {}).get('edges', [])
                if events:
                    # Get the first (most recent) delivery event
                    for event_edge in events:
                        event = event_edge['node']
                        if event.get('status') == 'DELIVERED':
                            print(f"    First DELIVERED event: {event.get('happenedAt')} - {event.get('message')}")
                            break
        else:
            print("No fulfillments in previous order")
    
    # Test the actual _get_previous_order_data method
    print(f"\n--- Testing _get_previous_order_data method ---")
    prev_delivery_status, prev_order_total = fraud_service._get_previous_order_data(order_data)
    print(f"Method returned - Delivery Status: {prev_delivery_status}, Total: {prev_order_total}")

if __name__ == "__main__":
    asyncio.run(test_delivery_status())