#!/usr/bin/env python3
"""
Test script to check what data we're getting from the fraud detection GraphQL query
"""
import asyncio
import sys
import os
import json

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

from shopify_client import ShopifyClient
from database import get_db
from models import ShopifyStore

async def test_fraud_data():
    """Test the fraud detection data retrieval"""
    
    # Get a store from the database
    db = next(get_db())
    store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
    
    if not store:
        print("No store found with ID 2")
        return
    
    print(f"Testing with store: {store.shop_name}")
    
    # Create client
    client = ShopifyClient(
        shop_domain=store.shop_domain,
        access_token=store.access_token
    )
    
    # Test with an order that has a customer
    order_name = "PW110446"
    print(f"Fetching fraud data for order: {order_name}")
    
    try:
        order_data = await client.get_order_fraud_data(order_name)
        
        if not order_data:
            print("No order data found")
            return
        
        print(f"Order data retrieved successfully")
        
        # Check customer data
        customer = order_data.get('customer', {})
        if not customer:
            print("No customer data found")
            return
            
        print(f"Customer email: {customer.get('email')}")
        print(f"Customer numberOfOrders: {customer.get('numberOfOrders')}")
        
        # Check customer order history
        customer_orders = customer.get('orders', {}).get('edges', [])
        print(f"Customer has {len(customer_orders)} orders in history")
        
        for i, order_edge in enumerate(customer_orders):
            order = order_edge['node']
            print(f"\n--- Order {i+1} ---")
            print(f"Name: {order.get('name')}")
            print(f"Created: {order.get('createdAt')}")
            print(f"Display fulfillment status: {order.get('displayFulfillmentStatus')}")
            
            fulfillments = order.get('fulfillments', [])
            print(f"Fulfillments count: {len(fulfillments)}")
            
            for j, fulfillment in enumerate(fulfillments):
                print(f"  Fulfillment {j+1}:")
                print(f"    Status: {fulfillment.get('status')}")
                print(f"    Display Status: {fulfillment.get('displayStatus')}")
                print(f"    Delivered At: {fulfillment.get('deliveredAt')}")
                print(f"    In Transit At: {fulfillment.get('inTransitAt')}")
                
                events = fulfillment.get('events', {}).get('edges', [])
                print(f"    Events count: {len(events)}")
                
                for k, event_edge in enumerate(events):
                    event = event_edge['node']
                    print(f"      Event {k+1}:")
                    print(f"        Status: {event.get('status')}")
                    print(f"        Happened At: {event.get('happenedAt')}")
                    print(f"        Message: {event.get('message')}")
                    
                tracking_info = fulfillment.get('trackingInfo', [])
                print(f"    Tracking Info count: {len(tracking_info)}")
                for t in tracking_info:
                    print(f"      Company: {t.get('company')}, Number: {t.get('number')}")
        
        # Save the full data to a file for inspection
        with open('/tmp/fraud_data_test.json', 'w') as f:
            json.dump(order_data, f, indent=2)
        print(f"\nFull order data saved to /tmp/fraud_data_test.json")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_fraud_data())