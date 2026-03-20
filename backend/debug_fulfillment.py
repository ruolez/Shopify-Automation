#!/usr/bin/env python3
"""
Debug script to check fulfillment location issues
Run this to diagnose why fulfillment location changes aren't working
"""

import asyncio
import json
import sys
import os

# Add backend path
sys.path.append('./backend')

from shopify_client import ShopifyClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

async def debug_fulfillment():
    """Debug fulfillment location issues"""

    print("=== SHOPIFY FULFILLMENT DEBUG ===\n")

    # Connect to database using environment variable (required)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is not set")
        print("Please set DATABASE_URL in your .env file or environment")
        sys.exit(1)

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Get store info
        result = session.execute(text('SELECT shop_domain, access_token FROM shopify_stores WHERE is_active = 1 LIMIT 1')).fetchone()
        if not result:
            print("❌ No active stores found in database")
            return
            
        shop_domain, access_token = result
        print(f"🏪 Store: {shop_domain}")
        
        # Create client
        client = ShopifyClient(shop_domain, access_token)
        
        # Test 1: Check locations
        print("\n1. 📍 Available Locations:")
        locations = await client.get_locations()
        for i, loc in enumerate(locations):
            print(f"   {i+1}. {loc['name']} - ID: {loc['id']}")
            if loc.get('address'):
                addr = loc['address']
                print(f"      Address: {addr.get('city', '')}, {addr.get('province', '')}, {addr.get('country', '')}")
        
        # Test 2: Get recent orders
        print(f"\n2. 📦 Recent Orders:")
        orders_data = await client.get_orders(limit=3)
        orders = orders_data["edges"]
        
        for order_edge in orders:
            order = order_edge["node"]
            order_name = order["name"]
            print(f"\n   Order: {order_name}")
            
            # Check fulfillment orders
            fulfillment_orders = order.get("fulfillmentOrders", {}).get("edges", [])
            print(f"   Fulfillment Orders: {len(fulfillment_orders)}")
            
            for fo_edge in fulfillment_orders:
                fo = fo_edge["node"]
                status = fo["status"]
                current_location = fo.get("assignedLocation", {}).get("location", {})
                location_name = current_location.get("name", "Unknown")
                location_id = current_location.get("id", "Unknown")
                
                print(f"     - Status: {status}")
                print(f"     - Current Location: {location_name} (ID: {location_id})")
                print(f"     - Can Move: {'✅' if status in ['open', 'scheduled'] else '❌'}")
        
        # Test 3: Check rules with fulfillment actions
        print(f"\n3. 🔧 Rules with Fulfillment Actions:")
        result = session.execute(text('SELECT id, name, actions FROM processing_rules WHERE is_active = 1')).fetchall()
        
        for rule_row in result:
            rule_id, rule_name, actions_json = rule_row
            actions = json.loads(actions_json) if actions_json else []
            
            fulfillment_actions = [a for a in actions if a.get("type") == "set_fulfillment_location"]
            if fulfillment_actions:
                print(f"\n   Rule: {rule_name} (ID: {rule_id})")
                for action in fulfillment_actions:
                    location_id = action.get("parameters", {}).get("location_id")
                    print(f"     - Target Location ID: {location_id}")
                    
                    # Check if location exists
                    location_exists = any(loc["id"] == location_id for loc in locations)
                    print(f"     - Location Valid: {'✅' if location_exists else '❌'}")
                    
                    if not location_exists:
                        print(f"     - ⚠️  Invalid location ID! Available IDs:")
                        for loc in locations:
                            print(f"         {loc['name']}: {loc['id']}")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        session.close()

if __name__ == "__main__":
    asyncio.run(debug_fulfillment())