#!/usr/bin/env python3
"""
Enhanced delivery tracking test for fraud detection system.
Tests the new comprehensive delivery status retrieval using Shopify MCP insights.
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
from models import ShopifyStore, User, FraudAnalysis

async def test_enhanced_delivery_tracking():
    """Test the enhanced delivery tracking system"""
    
    print("🔍 Testing Enhanced Delivery Tracking System")
    print("=" * 60)
    
    # Get a store and user from the database
    db = next(get_db())
    store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
    user = db.query(User).filter(User.id == 4).first()
    
    if not store or not user:
        print("❌ No store or user found")
        return
    
    print(f"🏪 Testing with store: {store.shop_name}")
    print(f"👤 User: {user.email}")
    
    # Create client and service
    client = ShopifyClient(
        shop_domain=store.shop_domain,
        access_token=store.access_token
    )
    
    fraud_service = FraudAnalysisService(db, store, user)
    
    # Test order
    order_name = "PW110446"  # Replace with actual order name from your store
    print(f"\n📦 Analyzing order: {order_name}")
    print("-" * 40)
    
    # Get enhanced order data
    print("🔄 Fetching enhanced order data with comprehensive fulfillment tracking...")
    order_data = await client.get_order_fraud_data(order_name)
    
    if not order_data:
        print("❌ No order data found")
        return
    
    print("✅ Order data retrieved successfully")
    
    # Test individual methods
    print("\n🧪 Testing Individual Delivery Tracking Methods:")
    print("-" * 50)
    
    # 1. Test current order delivery status
    print("1️⃣ Current Order Delivery Status:")
    current_status = fraud_service._extract_delivery_tracking_status(order_data)
    print(f"   📋 Status: {current_status}")
    
    # 2. Test previous order delivery status (boolean)
    print("\n2️⃣ Previous Order Delivery Status (Boolean):")
    prev_bool_status = fraud_service._get_previous_order_delivery_status(order_data)
    print(f"   ✅ Delivered: {prev_bool_status}")
    
    # 3. Test previous order delivery status (detailed)
    print("\n3️⃣ Previous Order Delivery Status (Detailed):")
    prev_detailed_status, prev_total = fraud_service._get_previous_order_data(order_data)
    print(f"   📋 Status: {prev_detailed_status}")
    print(f"   💰 Total: ${prev_total}")
    
    # 4. Test comprehensive delivery analytics
    print("\n4️⃣ Comprehensive Delivery Analytics:")
    analytics = fraud_service._get_comprehensive_delivery_analytics(order_data)
    print(f"   📊 Analytics Keys: {list(analytics.keys())}")
    
    print("\n   📈 Delivery History:")
    history = analytics['customer_delivery_history']
    print(f"      Total Orders: {history['total_orders']}")
    print(f"      Delivered Orders: {history['delivered_orders']}")
    print(f"      Failed Deliveries: {history['failed_deliveries']}")
    print(f"      Success Rate: {history['delivery_success_rate']:.2%}")
    print(f"      Avg Delivery Days: {history['average_delivery_days']}")
    
    print("\n   🔍 Delivery Patterns:")
    patterns = analytics['delivery_patterns']
    print(f"      Has Tracking Info: {patterns['has_tracking_info']}")
    print(f"      Multiple Attempts: {patterns['multiple_delivery_attempts']}")
    print(f"      Unusual Locations: {patterns['unusual_delivery_locations']}")
    
    # 5. Test full fraud analysis with enhanced delivery tracking
    print("\n5️⃣ Full Fraud Analysis with Enhanced Delivery Tracking:")
    print("-" * 55)
    
    try:
        fraud_analysis = fraud_service.analyze_order_fraud(order_data)
        
        if fraud_analysis:
            print("✅ Fraud analysis completed successfully")
            print(f"   📊 Analysis ID: {fraud_analysis.id}")
            print(f"   👤 First-time Customer: {fraud_analysis.is_first_time_customer}")
            print(f"   💰 Order Total: ${fraud_analysis.current_order_total}")
            print(f"   🚚 Current Delivery Status: {fraud_analysis.current_order_delivery_status}")
            print(f"   📋 Previous Delivery Status: {fraud_analysis.previous_order_delivery_status}")
            
            # Show delivery analytics if available
            if fraud_analysis.delivery_analytics:
                print(f"   📈 Delivery Analytics Available: ✅")
                print(f"   📊 Analytics Keys: {list(fraud_analysis.delivery_analytics.keys())}")
            else:
                print(f"   📈 Delivery Analytics Available: ❌")
                
        else:
            print("❌ Fraud analysis failed")
            
    except Exception as e:
        print(f"❌ Error in fraud analysis: {str(e)}")
    
    # 6. Show raw fulfillment data structure
    print("\n6️⃣ Raw Fulfillment Data Structure:")
    print("-" * 40)
    
    fulfillments = order_data.get('fulfillments', [])
    print(f"   📦 Number of fulfillments: {len(fulfillments)}")
    
    for i, fulfillment in enumerate(fulfillments):
        print(f"\n   📦 Fulfillment {i+1}:")
        print(f"      ID: {fulfillment.get('id')}")
        print(f"      Status: {fulfillment.get('status')}")
        print(f"      Display Status: {fulfillment.get('displayStatus')}")
        print(f"      Delivered At: {fulfillment.get('deliveredAt')}")
        print(f"      In Transit At: {fulfillment.get('inTransitAt')}")
        print(f"      Estimated Delivery: {fulfillment.get('estimatedDeliveryAt')}")
        
        events = fulfillment.get('events', {}).get('edges', [])
        print(f"      Events Count: {len(events)}")
        
        if events:
            print(f"      Recent Events:")
            for j, event_edge in enumerate(events[:3]):  # Show first 3 events
                event = event_edge['node']
                print(f"        {j+1}. {event.get('status')} at {event.get('happenedAt')}")
                if event.get('message'):
                    print(f"           Message: {event.get('message')}")
    
    # 7. Customer order history analysis
    customer = order_data.get('customer', {})
    if customer:
        print("\n7️⃣ Customer Order History Analysis:")
        print("-" * 40)
        
        customer_orders = customer.get('orders', {}).get('edges', [])
        print(f"   👤 Customer: {customer.get('firstName', '')} {customer.get('lastName', '')}")
        print(f"   📧 Email: {customer.get('email', '')}")
        print(f"   📊 Total Orders: {customer.get('numberOfOrders', 0)}")
        print(f"   📋 Orders in History: {len(customer_orders)}")
        
        for i, order_edge in enumerate(customer_orders[:3]):  # Show first 3 orders
            order = order_edge['node']
            print(f"\n   📦 Order {i+1}: {order.get('name')}")
            print(f"      Created: {order.get('createdAt')}")
            print(f"      Fulfillment Status: {order.get('displayFulfillmentStatus')}")
            
            order_fulfillments = order.get('fulfillments', [])
            if order_fulfillments:
                print(f"      Fulfillments: {len(order_fulfillments)}")
                for fulfillment in order_fulfillments:
                    if fulfillment.get('deliveredAt'):
                        print(f"        ✅ Delivered: {fulfillment.get('deliveredAt')}")
                    elif fulfillment.get('displayStatus'):
                        print(f"        📋 Status: {fulfillment.get('displayStatus')}")
    
    print("\n🎉 Enhanced Delivery Tracking Test Complete!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_enhanced_delivery_tracking())