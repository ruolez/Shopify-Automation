#!/usr/bin/env python3
"""
Debug the order sequence to see which order is actually the "previous" one
"""
import sys
import os
import asyncio
from datetime import datetime

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

async def debug_order_sequence():
    """Debug the order sequence to understand current vs previous order logic"""
    
    print("🔍 DEBUGGING ORDER SEQUENCE FOR PW15996")
    print("=" * 55)
    
    try:
        from database import get_db
        from models import User, ShopifyStore
        from shopify_client import ShopifyClient
        
        db = next(get_db())
        
        # Get the user and store
        user = db.query(User).filter(User.email == 'alexr@tobaccogeneral.com').first()
        store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
        
        client = ShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        # Get order data for PW15996
        order_data = await client.get_order_fraud_data('PW15996')
        
        if not order_data:
            print("❌ Could not fetch order data")
            return
            
        # Get the current order info
        order_info = order_data.get('order_info', {})
        current_order_name = order_info.get('name', 'Unknown')
        current_order_created = order_info.get('created_at', 'Unknown')
        
        print(f"🎯 CURRENT ORDER BEING ANALYZED:")
        print(f"   Name: {current_order_name}")
        print(f"   Created: {current_order_created}")
        
        # Get customer order history
        customer = order_data.get('customer', {})
        customer_orders = customer.get('orders', {}).get('edges', [])
        
        print(f"\n📊 CUSTOMER ORDER HISTORY ({len(customer_orders)} orders):")
        print("=" * 60)
        
        for i, order_edge in enumerate(customer_orders):
            order = order_edge['node']
            order_name = order.get('name', 'Unknown')
            order_created = order.get('createdAt', 'Unknown')
            fulfillments = order.get('fulfillments', [])
            
            # Parse creation date for comparison
            try:
                created_dt = datetime.fromisoformat(order_created.replace('Z', '+00:00'))
                created_formatted = created_dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                created_formatted = order_created
            
            print(f"   Order {i+1}: {order_name}")
            print(f"     Created: {created_formatted}")
            print(f"     Fulfillments: {len(fulfillments)}")
            
            # Show delivery info for each fulfillment
            for j, fulfillment in enumerate(fulfillments):
                delivered_at = fulfillment.get('deliveredAt')
                display_status = fulfillment.get('displayStatus', 'Unknown')
                
                if delivered_at:
                    try:
                        delivered_dt = datetime.fromisoformat(delivered_at.replace('Z', '+00:00'))
                        delivered_formatted = delivered_dt.strftime('%Y-%m-%d %H:%M:%S')
                        print(f"       Fulfillment {j+1}: DELIVERED on {delivered_formatted}")
                        
                        if '2024-08-05' in delivered_at:
                            print(f"       🎯 THIS IS THE AUGUST 5TH DELIVERY!")
                    except:
                        print(f"       Fulfillment {j+1}: DELIVERED (date parse error)")
                else:
                    print(f"       Fulfillment {j+1}: {display_status} (no delivery date)")
            
            # Check if this is the current order
            if order_name == current_order_name:
                print(f"     ⭐ THIS IS THE CURRENT ORDER")
            
            print()
        
        # Now let's see what the current logic thinks is the "previous" order
        print(f"🤔 CURRENT LOGIC ANALYSIS:")
        print("=" * 35)
        
        if len(customer_orders) >= 2:
            # Current logic: second order (index 1) is "previous"
            supposed_previous = customer_orders[1]['node']
            prev_name = supposed_previous.get('name', 'Unknown')
            prev_created = supposed_previous.get('createdAt', 'Unknown')
            prev_fulfillments = supposed_previous.get('fulfillments', [])
            
            print(f"Current logic says 'previous order' is:")
            print(f"   Name: {prev_name}")
            print(f"   Created: {prev_created}")
            print(f"   Fulfillments: {len(prev_fulfillments)}")
            
            # Check if this is actually older than the current order
            try:
                current_dt = datetime.fromisoformat(current_order_created.replace('Z', '+00:00'))
                prev_dt = datetime.fromisoformat(prev_created.replace('Z', '+00:00'))
                
                if prev_dt < current_dt:
                    print(f"   ✅ This IS actually previous (older)")
                    
                    # Show what delivery status this would extract
                    for j, fulfillment in enumerate(prev_fulfillments):
                        delivered_at = fulfillment.get('deliveredAt')
                        if delivered_at:
                            print(f"   📦 Fulfillment {j+1} delivered: {delivered_at}")
                            if '2024-08-05' in delivered_at:
                                print(f"   🎯 This contains August 5th data!")
                else:
                    print(f"   ❌ This is NEWER than current order (logic issue!)")
                    
            except Exception as e:
                print(f"   ⚠️  Could not compare dates: {e}")
        else:
            print(f"Customer has less than 2 orders - no previous order logic applies")
        
        # Let's also check what order should ACTUALLY be previous
        print(f"\n🎯 CORRECT PREVIOUS ORDER ANALYSIS:")
        print("=" * 45)
        
        # Find the actual previous order (chronologically before current order)
        try:
            current_dt = datetime.fromisoformat(current_order_created.replace('Z', '+00:00'))
            
            previous_orders = []
            for order_edge in customer_orders:
                order = order_edge['node']
                order_created = order.get('createdAt', 'Unknown')
                order_name = order.get('name', 'Unknown')
                
                if order_name != current_order_name:  # Not the current order
                    try:
                        order_dt = datetime.fromisoformat(order_created.replace('Z', '+00:00'))
                        if order_dt < current_dt:  # Older than current
                            previous_orders.append((order_dt, order))
                    except:
                        pass
            
            if previous_orders:
                # Sort by date (newest first among previous orders)
                previous_orders.sort(key=lambda x: x[0], reverse=True)
                actual_previous = previous_orders[0][1]
                
                actual_prev_name = actual_previous.get('name', 'Unknown')
                actual_prev_created = actual_previous.get('createdAt', 'Unknown')
                actual_prev_fulfillments = actual_previous.get('fulfillments', [])
                
                print(f"Actual chronological previous order:")
                print(f"   Name: {actual_prev_name}")
                print(f"   Created: {actual_prev_created}")
                print(f"   Fulfillments: {len(actual_prev_fulfillments)}")
                
                for j, fulfillment in enumerate(actual_prev_fulfillments):
                    delivered_at = fulfillment.get('deliveredAt')
                    if delivered_at:
                        print(f"   📦 Fulfillment {j+1}: {delivered_at}")
                        if '2024-08-05' in delivered_at:
                            print(f"   🎯 August 5th delivery found in ACTUAL previous order!")
            else:
                print(f"No chronologically previous orders found")
                
        except Exception as e:
            print(f"Error in previous order analysis: {e}")
            
    except Exception as e:
        print(f"❌ Error during order sequence debug: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎉 Order Sequence Debug Complete!")
    print("=" * 40)

if __name__ == "__main__":
    asyncio.run(debug_order_sequence())