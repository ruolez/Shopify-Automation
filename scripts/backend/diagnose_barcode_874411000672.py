#!/usr/bin/env python3
"""
Diagnostic script to investigate barcode 874411000672 discrepancy
Using the exact same logic as the inventory verification
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import DATABASE_URL
from models import ShopifyStore, Settings, User, LocationMapping, LocationAlias
from shopify_client import ShopifyClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def diagnose_barcode():
    barcode = "874411000672"
    
    # Create database session
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Get the active store (assuming user_id 1 for now - adjust if needed)
        store = db.query(ShopifyStore).filter(
            ShopifyStore.is_active == True
        ).first()
        
        if not store:
            print("No active store found!")
            return
            
        print(f"\n=== Diagnosing barcode {barcode} for store: {store.shop_name} ===\n")
        
        # Get user settings
        settings = db.query(Settings).filter(Settings.user_id == store.user_id).first()
        days_back = settings.inventory_verification_days_back if settings else 7
        excluded_tag = settings.inventory_verification_excluded_tag if settings else None
        
        print(f"Settings: days_back={days_back}, excluded_tag={excluded_tag}")
        
        # Create Shopify client
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        # First, let's get ALL unfulfilled orders (not just recent ones)
        print("\n1. Fetching ALL unfulfilled orders with this barcode...")
        
        all_orders_query = """
        query getAllUnfulfilledOrders($query: String!, $first: Int!, $after: String) {
            orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        createdAt
                        displayFulfillmentStatus
                        cancelledAt
                        tags
                        lineItems(first: 50) {
                            edges {
                                node {
                                    id
                                    quantity
                                    variant {
                                        barcode
                                        sku
                                        title
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    hasNextPage
                    endCursor
                }
            }
        }
        """
        
        # Query for ALL unfulfilled orders (no date filter)
        all_unfulfilled_filter = "(fulfillment_status:unshipped OR fulfillment_status:partial) AND NOT status:cancelled"
        
        all_orders = []
        cursor = None
        has_next = True
        
        while has_next:
            variables = {
                "query": all_unfulfilled_filter,
                "first": 50,
                "after": cursor
            }
            
            result = await client._make_graphql_request(all_orders_query, variables)
            orders_data = result.get("data", {}).get("orders", {})
            
            for edge in orders_data.get("edges", []):
                order = edge.get("node", {})
                # Check if this order has our barcode
                for line_edge in order.get("lineItems", {}).get("edges", []):
                    line_item = line_edge.get("node", {})
                    variant = line_item.get("variant", {})
                    if variant and variant.get("barcode") == barcode:
                        all_orders.append({
                            "order_name": order.get("name"),
                            "created_at": order.get("createdAt"),
                            "status": order.get("displayFulfillmentStatus"),
                            "tags": order.get("tags", []),
                            "quantity": line_item.get("quantity"),
                            "sku": variant.get("sku"),
                            "variant_title": variant.get("title")
                        })
            
            page_info = orders_data.get("pageInfo", {})
            has_next = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
            
            # Safety limit
            if len(all_orders) > 500:
                print("Reached safety limit of 500 orders")
                break
        
        print(f"\nFound {len(all_orders)} total unfulfilled orders with barcode {barcode}")
        
        # Calculate total committed quantity
        total_committed = sum(order["quantity"] for order in all_orders)
        print(f"Total committed quantity: {total_committed}")
        
        # Now run the verification query (with date filter)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        print(f"\n2. Running verification query (last {days_back} days, since {cutoff_date.isoformat()})")
        
        # Filter orders by date and excluded tag
        verified_orders = []
        excluded_by_date = []
        excluded_by_tag = []
        
        for order in all_orders:
            order_date = datetime.fromisoformat(order["created_at"].replace("Z", "+00:00"))
            
            # Check date
            if order_date < cutoff_date:
                excluded_by_date.append(order)
                continue
                
            # Check excluded tag
            if excluded_tag and excluded_tag in order["tags"]:
                excluded_by_tag.append(order)
                continue
                
            verified_orders.append(order)
        
        total_verified = sum(order["quantity"] for order in verified_orders)
        print(f"Total verified quantity: {total_verified}")
        
        print(f"\n=== DISCREPANCY ANALYSIS ===")
        print(f"Committed: {total_committed}")
        print(f"Verified: {total_verified}")
        print(f"Difference: {total_committed - total_verified}")
        
        if excluded_by_date:
            print(f"\n{len(excluded_by_date)} orders excluded by date (older than {days_back} days):")
            date_quantity = 0
            for order in excluded_by_date[:10]:  # Show first 10
                print(f"  - {order['order_name']} created {order['created_at']}: {order['quantity']} units")
                date_quantity += order["quantity"]
            if len(excluded_by_date) > 10:
                remaining_quantity = sum(o["quantity"] for o in excluded_by_date[10:])
                print(f"  ... and {len(excluded_by_date) - 10} more orders with {remaining_quantity} units")
            print(f"  Total excluded by date: {sum(o['quantity'] for o in excluded_by_date)} units")
        
        if excluded_by_tag:
            print(f"\n{len(excluded_by_tag)} orders excluded by tag '{excluded_tag}':")
            for order in excluded_by_tag[:5]:  # Show first 5
                print(f"  - {order['order_name']}: {order['quantity']} units (tags: {', '.join(order['tags'])})")
            if len(excluded_by_tag) > 5:
                print(f"  ... and {len(excluded_by_tag) - 5} more orders")
            print(f"  Total excluded by tag: {sum(o['quantity'] for o in excluded_by_tag)} units")
        
        # Now let's also check inventory levels directly
        print(f"\n3. Checking inventory levels directly...")
        
        # First find the variant
        variant_query = """
        query findVariant($query: String!) {
            productVariants(first: 1, query: $query) {
                edges {
                    node {
                        id
                        barcode
                        sku
                        inventoryItem {
                            id
                            inventoryLevels(first: 10) {
                                edges {
                                    node {
                                        id
                                        available
                                        incoming
                                        committed
                                        location {
                                            id
                                            name
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        variant_result = await client._make_graphql_request(
            variant_query, 
            {"query": f"barcode:{barcode}"}
        )
        
        variant_data = variant_result.get("data", {}).get("productVariants", {}).get("edges", [])
        if variant_data:
            variant = variant_data[0].get("node", {})
            inventory_item = variant.get("inventoryItem", {})
            print(f"\nVariant SKU: {variant.get('sku')}")
            
            inventory_levels = inventory_item.get("inventoryLevels", {}).get("edges", [])
            for level_edge in inventory_levels:
                level = level_edge.get("node", {})
                location = level.get("location", {})
                print(f"\nLocation: {location.get('name')}")
                print(f"  Available: {level.get('available')}")
                print(f"  Committed: {level.get('committed')}")
                print(f"  Incoming: {level.get('incoming')}")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(diagnose_barcode())