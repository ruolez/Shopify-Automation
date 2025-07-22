#!/usr/bin/env python3
"""
Test script to run fraud analysis on a specific order and check previous delivery status
"""
import sys
import os
import asyncio
from datetime import datetime

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

from fraud_service import FraudAnalysisService
from shopify_client import ShopifyClient
from database import get_db
from models import ShopifyStore, User

async def test_fraud_analysis_delivery():
    """Test fraud analysis delivery status extraction"""
    
    print("🔍 TESTING FRAUD ANALYSIS DELIVERY STATUS EXTRACTION")
    print("=" * 65)
    
    # Get store and user
    db = next(get_db())
    store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
    user = db.query(User).filter(User.id == 4).first()
    
    if not store or not user:
        print("❌ No store or user found")
        return
    
    print(f"🏪 Store: {store.shop_name}")
    print(f"👤 User: {user.email}")
    
    # Create fraud service and client
    fraud_service = FraudAnalysisService(db, store, user)
    client = ShopifyClient(
        shop_domain=store.shop_domain,
        access_token=store.access_token
    )
    
    # Test order from user's example showing August 5th 2024 delivery
    order_name = "PW15996"  # This is the order the user mentioned with August 5th delivery
    
    print(f"\n📦 Testing fraud analysis for order: {order_name}")
    print("=" * 55)
    
    try:
        # Get order data first
        print("1️⃣ Fetching order data...")
        order_data = await client.get_order_fraud_data(order_name)
        
        if not order_data:
            print("❌ Failed to fetch order data")
            return
            
        print("✅ Order data fetched successfully")
        
        # Check if customer has order history
        customer = order_data.get('customer', {})
        if customer:
            customer_orders = customer.get('orders', {}).get('edges', [])
            print(f"📊 Customer has {len(customer_orders)} orders in history")
            
            # Show previous orders for context
            for i, order_edge in enumerate(customer_orders[:3]):
                order = order_edge['node']
                order_name_hist = order.get('name', 'Unknown')
                fulfillments = order.get('fulfillments', [])
                print(f"   Order {i+1}: {order_name_hist} ({len(fulfillments)} fulfillments)")
                
                # Show delivery info for each fulfillment
                for j, fulfillment in enumerate(fulfillments):
                    delivered_at = fulfillment.get('deliveredAt')
                    display_status = fulfillment.get('displayStatus')
                    print(f"     Fulfillment {j+1}: deliveredAt={delivered_at}, status={display_status}")
                    
                    # Parse and format the August 5th date if found
                    if delivered_at and '2024-08-05' in delivered_at:
                        try:
                            delivery_datetime = datetime.fromisoformat(delivered_at.replace('Z', '+00:00'))
                            formatted_date = delivery_datetime.strftime('%B %d, %Y')
                            print(f"     🎯 FOUND AUGUST 5TH DELIVERY: {formatted_date}")
                        except Exception as e:
                            print(f"     ❌ Date parsing error: {e}")
        
        # Run fraud analysis
        print(f"\n2️⃣ Running fraud analysis...")
        analysis = fraud_service.analyze_order_fraud(order_data)
        
        if analysis:
            print("✅ Fraud analysis completed successfully!")
            print(f"   Analysis ID: {analysis.id}")
            print(f"   Order: {analysis.order_name}")
            print(f"   First-time Customer: {analysis.is_first_time_customer}")
            print(f"   Current Delivery Status: '{analysis.current_order_delivery_status}'")
            print(f"   Previous Delivery Status: '{analysis.previous_order_delivery_status}'")
            print(f"   Previous Order Total: ${analysis.previous_order_total}")
            
            # Check if we got the August 5th data
            if analysis.previous_order_delivery_status:
                if 'august' in analysis.previous_order_delivery_status.lower() and '2024' in analysis.previous_order_delivery_status:
                    print("🎯 SUCCESS: August 5th 2024 delivery data detected in analysis!")
                elif '2024-08-05' in str(analysis.previous_order_delivery_status):
                    print("🎯 SUCCESS: August 5th 2024 delivery data detected (ISO format)!")
                else:
                    print(f"⚠️  Previous delivery status found but doesn't contain August 2024: '{analysis.previous_order_delivery_status}'")
            else:
                print("❌ Previous delivery status is None/empty")
            
            # Show delivery analytics if available
            if hasattr(analysis, 'delivery_analytics') and analysis.delivery_analytics:
                print(f"\n📊 Delivery Analytics Available:")
                analytics = analysis.delivery_analytics
                if isinstance(analytics, dict):
                    prev_status = analytics.get('previous_order_delivery_status')
                    if prev_status:
                        print(f"   Analytics Previous Status: '{prev_status}'")
                    
                    history = analytics.get('customer_delivery_history', {})
                    total_orders = history.get('total_orders', 0)
                    delivered_orders = history.get('delivered_orders', 0)
                    success_rate = history.get('delivery_success_rate', 0)
                    print(f"   Customer History: {delivered_orders}/{total_orders} delivered ({success_rate:.1%})")
        else:
            print("❌ Fraud analysis failed")
            
    except Exception as e:
        print(f"❌ Error during fraud analysis test: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎉 Fraud Analysis Delivery Test Complete!")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(test_fraud_analysis_delivery())