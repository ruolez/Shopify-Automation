#!/usr/bin/env python3
"""
Debug script to analyze delivery status extraction from Shopify API
"""
import asyncio
import sys
import os
import json
from datetime import datetime

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

from fraud_service import FraudAnalysisService
from shopify_client import ShopifyClient
from database import get_db
from models import ShopifyStore, User

async def debug_delivery_status():
    """Debug the delivery status extraction process"""
    
    print("🔍 DEBUGGING DELIVERY STATUS EXTRACTION")
    print("=" * 60)
    
    # Get a store and user from the database
    db = next(get_db())
    store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
    user = db.query(User).filter(User.id == 4).first()
    
    if not store or not user:
        print("❌ No store or user found")
        return
    
    print(f"🏪 Store: {store.shop_name}")
    print(f"👤 User: {user.email}")
    
    # Create client and service
    client = ShopifyClient(
        shop_domain=store.shop_domain,
        access_token=store.access_token
    )
    
    fraud_service = FraudAnalysisService(db, store, user)
    
    # Test order - replace with the actual order name you're testing
    order_name = input("Enter the order name to debug (e.g., PW110446): ").strip()
    if not order_name:
        print("❌ No order name provided")
        return
    
    print(f"\n📦 Debugging order: {order_name}")
    print("=" * 50)
    
    # Get order data from Shopify
    print("🔄 Fetching order data from Shopify...")
    order_data = await client.get_order_fraud_data(order_name)
    
    if not order_data:
        print("❌ No order data found")
        return
    
    print("✅ Order data retrieved successfully")
    
    # Debug customer data structure
    print("\n1️⃣ CUSTOMER DATA ANALYSIS")
    print("-" * 40)
    
    customer = order_data.get('customer', {})
    if not customer:
        print("❌ No customer data found")
        return
    
    print(f"Customer ID: {customer.get('id')}")
    print(f"Customer Email: {customer.get('email')}")
    print(f"Customer Name: {customer.get('firstName', '')} {customer.get('lastName', '')}")
    print(f"Number of Orders: {customer.get('numberOfOrders', 0)}")
    
    # Analyze customer order history
    customer_orders = customer.get('orders', {}).get('edges', [])
    print(f"Orders in history: {len(customer_orders)}")
    
    if len(customer_orders) < 2:
        print("❌ Need at least 2 orders (current + previous) for previous order analysis")
        return
    
    print(f"\n2️⃣ ORDER HISTORY ANALYSIS")
    print("-" * 40)
    
    for i, order_edge in enumerate(customer_orders[:3]):  # Show first 3 orders
        order = order_edge['node']
        order_name_hist = order.get('name', 'Unknown')
        created_at = order.get('createdAt', 'Unknown')
        fulfillment_status = order.get('displayFulfillmentStatus', 'Unknown')
        
        print(f"\nOrder {i+1}: {order_name_hist}")
        print(f"  Created: {created_at}")
        print(f"  Fulfillment Status: {fulfillment_status}")
        
        # Analyze fulfillments for this order
        fulfillments = order.get('fulfillments', [])
        print(f"  Fulfillments Count: {len(fulfillments)}")
        
        for j, fulfillment in enumerate(fulfillments):
            print(f"\n    Fulfillment {j+1}:")
            print(f"      ID: {fulfillment.get('id')}")
            print(f"      Status: {fulfillment.get('status')}")
            print(f"      Display Status: {fulfillment.get('displayStatus')}")
            print(f"      Delivered At: {fulfillment.get('deliveredAt')}")
            print(f"      In Transit At: {fulfillment.get('inTransitAt')}")
            print(f"      Estimated Delivery: {fulfillment.get('estimatedDeliveryAt')}")
            print(f"      Created At: {fulfillment.get('createdAt')}")
            print(f"      Updated At: {fulfillment.get('updatedAt')}")
            
            # Analyze fulfillment events
            events = fulfillment.get('events', {}).get('edges', [])
            print(f"      Events Count: {len(events)}")
            
            if events:
                print(f"      Events (most recent first):")
                for k, event_edge in enumerate(events[:5]):  # Show first 5 events
                    event = event_edge['node']
                    event_status = event.get('status', 'Unknown')
                    happened_at = event.get('happenedAt', 'Unknown')
                    message = event.get('message', '')
                    
                    print(f"        {k+1}. {event_status} at {happened_at}")
                    if message:
                        print(f"           Message: {message}")
    
    # Test the previous order analysis specifically
    print(f"\n3️⃣ PREVIOUS ORDER DELIVERY STATUS TESTING")
    print("-" * 50)
    
    # Test the boolean method
    print("Testing _get_previous_order_delivery_status()...")
    prev_bool_status = fraud_service._get_previous_order_delivery_status(order_data)
    print(f"Result (boolean): {prev_bool_status}")
    
    # Test the detailed method
    print("\nTesting _get_previous_order_data()...")
    prev_detailed_status, prev_total = fraud_service._get_previous_order_data(order_data)
    print(f"Result (detailed): {prev_detailed_status}")
    print(f"Previous order total: {prev_total}")
    
    # Test current order delivery status for comparison
    print(f"\n4️⃣ CURRENT ORDER DELIVERY STATUS")
    print("-" * 40)
    
    current_status = fraud_service._extract_delivery_tracking_status(order_data)
    print(f"Current order delivery status: {current_status}")
    
    # Manual analysis of the previous order (second in the list)
    print(f"\n5️⃣ MANUAL ANALYSIS OF PREVIOUS ORDER")
    print("-" * 45)
    
    if len(customer_orders) >= 2:
        previous_order = customer_orders[1]['node']
        prev_order_name = previous_order.get('name')
        print(f"Previous order name: {prev_order_name}")
        
        # Create a mock order data structure for the previous order
        previous_order_mock = {
            'fulfillments': previous_order.get('fulfillments', [])
        }
        
        print(f"Previous order fulfillments: {len(previous_order_mock['fulfillments'])}")
        
        # Test our extraction method on the previous order
        manual_status = fraud_service._extract_delivery_tracking_status(previous_order_mock)
        print(f"Manual extraction result: {manual_status}")
        
        # Check if the August 5th 2024 delivery is in the data
        for fulfillment in previous_order_mock['fulfillments']:
            delivered_at = fulfillment.get('deliveredAt')
            if delivered_at:
                try:
                    delivery_date = datetime.fromisoformat(delivered_at.replace('Z', '+00:00'))
                    formatted_date = delivery_date.strftime('%B %d, %Y')
                    print(f"📅 Found delivery date: {formatted_date}")
                    
                    if delivery_date.month == 8 and delivery_date.day == 5 and delivery_date.year == 2024:
                        print("✅ FOUND: August 5th, 2024 delivery!")
                    
                except Exception as e:
                    print(f"Error parsing delivery date {delivered_at}: {e}")
    
    # Test comprehensive delivery analytics
    print(f"\n6️⃣ COMPREHENSIVE DELIVERY ANALYTICS")
    print("-" * 45)
    
    analytics = fraud_service._get_comprehensive_delivery_analytics(order_data)
    print(f"Previous order delivery status (from analytics): {analytics.get('previous_order_delivery_status')}")
    
    history = analytics.get('customer_delivery_history', {})
    print(f"Total orders: {history.get('total_orders')}")
    print(f"Delivered orders: {history.get('delivered_orders')}")
    print(f"Failed deliveries: {history.get('failed_deliveries')}")
    print(f"Success rate: {history.get('delivery_success_rate', 0):.1%}")
    
    print(f"\n🎯 DEBUGGING COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(debug_delivery_status())