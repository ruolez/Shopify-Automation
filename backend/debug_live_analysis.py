#!/usr/bin/env python3
"""
Debug the live analysis that the frontend is creating
"""
import sys
import os

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

def debug_live_analysis():
    """Debug what happens when we analyze PW15996 live"""
    
    print("🔍 DEBUGGING LIVE ANALYSIS FOR PW15996")
    print("=" * 50)
    
    try:
        from database import get_db
        from models import User, ShopifyStore, FraudAnalysis
        from fraud_service import FraudAnalysisService
        from shopify_client import ShopifyClient
        import asyncio
        
        db = next(get_db())
        
        # Get the user and store
        user = db.query(User).filter(User.email == 'alexr@tobaccogeneral.com').first()
        store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()  # Primewholesale.com
        
        if not user or not store:
            print("❌ User or store not found")
            return
            
        print(f"✅ User: {user.email} (ID: {user.id})")
        print(f"✅ Store: {store.shop_name} (ID: {store.id})")
        
        # Check existing analyses
        existing_analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user.id,
            FraudAnalysis.order_name == 'PW15996'
        ).all()
        
        print(f"\n📊 EXISTING ANALYSES for PW15996:")
        for analysis in existing_analyses:
            print(f"   ID {analysis.id}: '{analysis.previous_order_delivery_status}'")
        
        # Delete existing analyses for fresh test
        for analysis in existing_analyses:
            db.delete(analysis)
        db.commit()
        print(f"🗑️  Deleted {len(existing_analyses)} existing analyses for fresh test")
        
        # Create fraud service and client
        fraud_service = FraudAnalysisService(db, store, user)
        client = ShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        async def run_analysis():
            print(f"\n🔄 RUNNING FRESH ANALYSIS...")
            
            # Get order data from Shopify
            order_data = await client.get_order_fraud_data('PW15996')
            
            if not order_data:
                print("❌ Could not fetch order data from Shopify")
                return
                
            print("✅ Order data fetched from Shopify")
            
            # Check customer order history in the raw data
            customer = order_data.get('customer', {})
            if customer:
                customer_orders = customer.get('orders', {}).get('edges', [])
                print(f"📊 Customer has {len(customer_orders)} orders in history")
                
                # Show the previous orders and their delivery data
                for i, order_edge in enumerate(customer_orders[:3]):
                    order = order_edge['node']
                    order_name = order.get('name', 'Unknown')
                    fulfillments = order.get('fulfillments', [])
                    
                    print(f"   Order {i+1}: {order_name}")
                    for j, fulfillment in enumerate(fulfillments):
                        delivered_at = fulfillment.get('deliveredAt')
                        display_status = fulfillment.get('displayStatus')
                        print(f"     Fulfillment {j+1}: deliveredAt={delivered_at}, status={display_status}")
                        
                        if delivered_at and '2024-08-05' in delivered_at:
                            print(f"     🎯 FOUND AUGUST 5TH DATA IN RAW SHOPIFY RESPONSE!")
            
            # Run the fraud analysis
            analysis = fraud_service.analyze_order_fraud(order_data)
            
            if analysis:
                print(f"\n✅ NEW ANALYSIS CREATED:")
                print(f"   Analysis ID: {analysis.id}")
                print(f"   Order: {analysis.order_name}")
                print(f"   Previous Delivery Status: '{analysis.previous_order_delivery_status}'")
                print(f"   Current Delivery Status: '{analysis.current_order_delivery_status}'")
                print(f"   First Time Customer: {analysis.is_first_time_customer}")
                
                # Check what the _get_previous_order_data method specifically returns
                print(f"\n🔍 TESTING PREVIOUS ORDER DATA EXTRACTION...")
                prev_status, prev_total = fraud_service._get_previous_order_data(order_data)
                print(f"   _get_previous_order_data returned: '{prev_status}', ${prev_total}")
                
                if prev_status is None:
                    print(f"❌ ISSUE: _get_previous_order_data returned None")
                    
                    # Debug why it's None
                    customer = order_data.get('customer', {})
                    customer_orders = customer.get('orders', {}).get('edges', [])
                    print(f"   Customer orders count: {len(customer_orders)}")
                    
                    if len(customer_orders) >= 2:
                        previous_order = customer_orders[1]['node']
                        prev_order_name = previous_order.get('name', 'Unknown')
                        fulfillments = previous_order.get('fulfillments', [])
                        print(f"   Previous order: {prev_order_name} with {len(fulfillments)} fulfillments")
                        
                        if fulfillments:
                            # Test the extraction directly
                            previous_order_mock = {'fulfillments': fulfillments}
                            delivery_status = fraud_service._extract_delivery_tracking_status(previous_order_mock)
                            print(f"   _extract_delivery_tracking_status returned: '{delivery_status}'")
                            
                            # Check the filtering logic
                            if delivery_status and delivery_status.lower() not in ['unknown', 'unfulfilled', 'none', '']:
                                print(f"   ✅ Should pass filter: '{delivery_status}'")
                            else:
                                print(f"   ❌ Failed filter: '{delivery_status}'")
                        else:
                            print(f"   ❌ No fulfillments in previous order")
                    else:
                        print(f"   ❌ Less than 2 orders in customer history")
                elif 'august' in prev_status.lower() and '2024' in prev_status:
                    print(f"   ✅ SUCCESS: August 2024 data extracted!")
                else:
                    print(f"   ⚠️  Unexpected previous order status: '{prev_status}'")
            else:
                print("❌ Analysis failed")
        
        # Run the async analysis
        asyncio.run(run_analysis())
        
    except Exception as e:
        print(f"❌ Error during live analysis debug: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎉 Live Analysis Debug Complete!")
    print("=" * 40)

if __name__ == "__main__":
    debug_live_analysis()