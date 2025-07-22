#!/usr/bin/env python3
"""
Debug PW110472 analysis to see what previous order it finds
"""
import sys
import os
import asyncio

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

async def debug_pw110472_analysis():
    """Debug what happens when we analyze PW110472"""
    
    print("🔍 DEBUGGING PW110472 ANALYSIS (Looking for PW15996 as previous)")
    print("=" * 70)
    
    try:
        from database import get_db
        from models import User, ShopifyStore, FraudAnalysis
        from fraud_service import FraudAnalysisService
        from shopify_client import ShopifyClient
        
        db = next(get_db())
        
        # Get the user and store
        user = db.query(User).filter(User.email == 'alexr@tobaccogeneral.com').first()
        store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
        
        # Delete existing analysis for PW110472 for fresh test
        existing = db.query(FraudAnalysis).filter(FraudAnalysis.order_name == 'PW110472').first()
        if existing:
            db.delete(existing)
            db.commit()
            print("🗑️  Deleted existing PW110472 analysis for fresh test")
        
        # Create fraud service and client
        fraud_service = FraudAnalysisService(db, store, user)
        client = ShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        # Get order data for PW110472
        print(f"\n📦 FETCHING ORDER DATA FOR PW110472...")
        order_data = await client.get_order_fraud_data('PW110472')
        
        if not order_data:
            print("❌ Could not fetch PW110472 order data")
            return
            
        print("✅ PW110472 order data fetched")
        
        # Check the current order info
        order_info = order_data.get('order_info', {})
        current_order_name = order_info.get('name', 'Unknown')
        current_order_created = order_info.get('created_at', 'Unknown')
        
        print(f"\n🎯 CURRENT ORDER INFO:")
        print(f"   Name: {current_order_name}")
        print(f"   Created: {current_order_created}")
        
        # Check customer order history
        customer = order_data.get('customer', {})
        customer_orders = customer.get('orders', {}).get('edges', [])
        
        print(f"\n📊 CUSTOMER ORDER HISTORY for PW110472 analysis:")
        for i, order_edge in enumerate(customer_orders):
            order = order_edge['node']
            order_name = order.get('name', 'Unknown')
            order_created = order.get('createdAt', 'Unknown')
            fulfillments = order.get('fulfillments', [])
            
            print(f"   Order {i+1}: {order_name} created {order_created}")
            
            if order_name == 'PW15996':
                print(f"   🎯 Found PW15996! Should be the previous order")
                for j, fulfillment in enumerate(fulfillments):
                    delivered_at = fulfillment.get('deliveredAt')
                    if delivered_at and '2024-08-05' in delivered_at:
                        print(f"      ✅ Has August 5th delivery: {delivered_at}")
        
        # Test the previous order detection logic
        print(f"\n🔍 TESTING PREVIOUS ORDER DETECTION...")
        prev_status, prev_total = fraud_service._get_previous_order_data(order_data)
        
        print(f"Result:")
        print(f"   Previous delivery status: '{prev_status}'")
        print(f"   Previous order total: ${prev_total}")
        
        if prev_status and 'august' in prev_status.lower() and '2024' in prev_status:
            print(f"   ✅ SUCCESS: Found August 5th 2024 delivery!")
        elif prev_status is None:
            print(f"   ❌ ISSUE: Previous delivery status is None")
        else:
            print(f"   ⚠️  Unexpected: '{prev_status}'")
        
        # Run full analysis
        print(f"\n🔄 RUNNING FULL ANALYSIS FOR PW110472...")
        analysis = fraud_service.analyze_order_fraud(order_data)
        
        if analysis:
            print(f"\n📊 ANALYSIS RESULTS:")
            print(f"   Analysis ID: {analysis.id}")
            print(f"   Order: {analysis.order_name}")
            print(f"   Previous Delivery Status: '{analysis.previous_order_delivery_status}'")
            print(f"   Current Delivery Status: '{analysis.current_order_delivery_status}'")
            
            if analysis.previous_order_delivery_status and 'august' in analysis.previous_order_delivery_status.lower():
                print(f"\n✅ SUCCESS: PW110472 analysis shows August 5th delivery for previous order!")
            elif analysis.previous_order_delivery_status is None:
                print(f"\n❌ PROBLEM: Previous delivery status is None - this is the N/A issue!")
            else:
                print(f"\n⚠️  Unexpected result: '{analysis.previous_order_delivery_status}'")
        else:
            print("❌ Analysis failed")
            
    except Exception as e:
        print(f"❌ Error during PW110472 analysis debug: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎉 PW110472 Analysis Debug Complete!")
    print("=" * 45)

if __name__ == "__main__":
    asyncio.run(debug_pw110472_analysis())