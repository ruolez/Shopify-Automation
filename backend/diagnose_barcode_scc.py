#!/usr/bin/env python3
"""
Diagnostic script to investigate barcode 874411000672 discrepancy for SCC location
Using the exact same logic as the inventory verification
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import DATABASE_URL
from models import ShopifyStore, Settings, User, LocationMapping, LocationAlias
from shopify_client import ShopifyClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def diagnose_barcode_scc():
    barcode = "874411000672"
    location_alias = "SC"
    
    # Create database session
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Get the active store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.is_active == True
        ).first()
        
        if not store:
            print("No active store found!")
            return
            
        print(f"\n=== Diagnosing barcode {barcode} for location {location_alias} ===")
        print(f"Store: {store.shop_name}\n")
        
        # Get the location ID for SCC
        alias = db.query(LocationAlias).filter(
            LocationAlias.user_id == store.user_id,
            LocationAlias.alias_name == location_alias,
            LocationAlias.is_active == True
        ).first()
        
        if not alias:
            print(f"Location alias {location_alias} not found!")
            return
            
        # Get the location mapping
        mapping = db.query(LocationMapping).filter(
            LocationMapping.alias_id == alias.id,
            LocationMapping.store_id == store.id,
            LocationMapping.is_active == True
        ).first()
        
        if not mapping:
            print(f"No mapping found for {location_alias} in store {store.shop_name}")
            return
            
        location_id = mapping.shopify_location_id
        print(f"Location ID: {location_id}")
        print(f"Location Name: {mapping.shopify_location_name}")
        
        # Get user settings
        settings = db.query(Settings).filter(Settings.user_id == store.user_id).first()
        days_back = settings.inventory_verification_days_back if settings else 7
        excluded_tag = settings.inventory_verification_excluded_tag if settings else None
        
        print(f"\nSettings:")
        print(f"  Days back: {days_back}")
        print(f"  Excluded tag: {excluded_tag}")
        
        # Create Shopify client
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        # First, get the inventory levels for this barcode at SCC
        print(f"\n1. Getting inventory levels for barcode at {location_alias}...")
        
        variant_query = """
        query findVariant($query: String!) {
            productVariants(first: 1, query: $query) {
                edges {
                    node {
                        id
                        barcode
                        sku
                        title
                        product {
                            title
                        }
                        inventoryItem {
                            id
                            inventoryLevels(first: 10) {
                                edges {
                                    node {
                                        id
                                        quantities(names: ["available", "on_hand", "committed", "incoming"]) {
                                            name
                                            quantity
                                        }
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
        if not variant_data:
            print("No variant found with this barcode!")
            return
            
        variant = variant_data[0].get("node", {})
        product = variant.get("product", {})
        print(f"\nProduct: {product.get('title')}")
        print(f"Variant: {variant.get('title')}")
        print(f"SKU: {variant.get('sku')}")
        
        # Find the inventory level for our location
        inventory_item = variant.get("inventoryItem", {})
        inventory_levels = inventory_item.get("inventoryLevels", {}).get("edges", [])
        
        scc_level = None
        quantities = {}
        for level_edge in inventory_levels:
            level = level_edge.get("node", {})
            if level.get("location", {}).get("id") == location_id:
                scc_level = level
                break
        
        if scc_level:
            for q in scc_level.get('quantities', []):
                quantities[q.get("name")] = q.get("quantity", 0)
            
            print(f"\nInventory at {location_alias}:")
            print(f"  Available: {quantities.get('available', 0)}")
            print(f"  Committed: {quantities.get('committed', 0)}")
            print(f"  Incoming: {quantities.get('incoming', 0)}")
            print(f"  On Hand: {quantities.get('on_hand', 0)}")
        else:
            print(f"\nNo inventory found at {location_alias}")
            return
        
        # Now run the verification query using the EXACT same logic as inventory verification
        print(f"\n2. Running verification query (last {days_back} days)...")
        
        cutoff_date = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
        
        # Build query filter - EXACT same as in shopify_client.py
        query_parts = [
            f"created_at:>={cutoff_date}",
            "(fulfillment_status:unshipped OR fulfillment_status:partial)",
            "NOT status:cancelled"
        ]
        
        if excluded_tag:
            query_parts.append(f"tag_not:{excluded_tag}")
            
        query_filter = " AND ".join(query_parts)
        print(f"\nQuery filter: {query_filter}")
        
        # Use the location-filtered query
        orders_query = """
        query getUnfulfilledOrdersForVerification($query: String!, $first: Int!, $after: String) {
            orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        createdAt
                        displayFulfillmentStatus
                        tags
                        fulfillmentOrders(first: 5) {
                            edges {
                                node {
                                    id
                                    status
                                    assignedLocation {
                                        location {
                                            id
                                            name
                                        }
                                    }
                                    lineItems(first: 50) {
                                        edges {
                                            node {
                                                id
                                                remainingQuantity
                                                lineItem {
                                                    variant {
                                                        barcode
                                                        sku
                                                    }
                                                }
                                            }
                                        }
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
        
        total_quantity = 0
        cursor = None
        has_next_page = True
        processed_orders = 0
        orders_with_barcode = []
        
        while has_next_page:
            variables = {
                "query": query_filter,
                "first": 20,  # Same as verification
                "after": cursor
            }
            
            result = await client._make_graphql_request(orders_query, variables)
            
            orders_data = result.get("data", {}).get("orders", {})
            edges = orders_data.get("edges", [])
            page_info = orders_data.get("pageInfo", {})
            
            # Process each order
            for edge in edges:
                order = edge.get("node", {})
                order_name = order.get("name")
                order_created = order.get("createdAt")
                order_tags = order.get("tags", [])
                
                # Check fulfillment orders for this location
                fulfillment_orders = order.get("fulfillmentOrders", {}).get("edges", [])
                
                for fo_edge in fulfillment_orders:
                    fo = fo_edge.get("node", {})
                    assigned_location = fo.get("assignedLocation", {}).get("location", {})
                    
                    # Check if this fulfillment order is assigned to SCC
                    if assigned_location.get("id") == location_id:
                        # Process line items
                        fo_line_items = fo.get("lineItems", {}).get("edges", [])
                        for fo_line_edge in fo_line_items:
                            fo_line = fo_line_edge.get("node", {})
                            line_variant = fo_line.get("lineItem", {}).get("variant", {})
                            
                            # Check if barcode matches
                            if line_variant and line_variant.get("barcode") == barcode:
                                remaining_qty = fo_line.get("remainingQuantity", 0)
                                total_quantity += remaining_qty
                                
                                orders_with_barcode.append({
                                    "order": order_name,
                                    "created": order_created,
                                    "quantity": remaining_qty,
                                    "tags": order_tags,
                                    "sku": line_variant.get("sku")
                                })
                                
                                print(f"\n  Found in order {order_name}:")
                                print(f"    Created: {order_created}")
                                print(f"    Remaining quantity: {remaining_qty}")
                                print(f"    Tags: {', '.join(order_tags) if order_tags else 'None'}")
                
                processed_orders += 1
            
            # Check for next page
            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
            
            # Same limit as verification
            if processed_orders >= 200:
                print(f"\n⚠️  Reached order processing limit of 200")
                break
        
        print(f"\n=== RESULTS ===")
        print(f"Processed {processed_orders} orders")
        print(f"Found {len(orders_with_barcode)} orders with barcode {barcode} at {location_alias}")
        committed_qty = quantities.get('committed', 0)
        print(f"\nShopify Committed: {committed_qty}")
        print(f"Verification Total: {total_quantity}")
        print(f"Difference: {committed_qty - total_quantity}")
        
        # Now let's check if there are any older orders
        if committed_qty > total_quantity:
            print(f"\n3. Checking for orders older than {days_back} days...")
            
            # Query without date filter to find all unfulfilled orders
            all_query_parts = [
                "(fulfillment_status:unshipped OR fulfillment_status:partial)",
                "NOT status:cancelled"
            ]
            all_query_filter = " AND ".join(all_query_parts)
            
            cursor = None
            has_next_page = True
            older_orders = []
            
            checked_orders = 0
            while has_next_page and len(older_orders) < 50 and checked_orders < 1000:  # Limit to 50 older orders or 1000 checks
                variables = {
                    "query": all_query_filter,
                    "first": 20,
                    "after": cursor
                }
                
                result = await client._make_graphql_request(orders_query, variables)
                orders_data = result.get("data", {}).get("orders", {})
                edges = orders_data.get("edges", [])
                
                for edge in edges:
                    checked_orders += 1
                    order = edge.get("node", {})
                    order_created = datetime.fromisoformat(order.get("createdAt").replace("Z", "+00:00"))
                    cutoff_datetime = datetime.fromisoformat(cutoff_date).replace(tzinfo=order_created.tzinfo)
                    
                    # Skip if within date range
                    if order_created >= cutoff_datetime:
                        continue
                    
                    # Check for our barcode at SCC
                    fulfillment_orders = order.get("fulfillmentOrders", {}).get("edges", [])
                    for fo_edge in fulfillment_orders:
                        fo = fo_edge.get("node", {})
                        if fo.get("assignedLocation", {}).get("location", {}).get("id") == location_id:
                            fo_line_items = fo.get("lineItems", {}).get("edges", [])
                            for fo_line_edge in fo_line_items:
                                fo_line = fo_line_edge.get("node", {})
                                line_variant = fo_line.get("lineItem", {}).get("variant", {})
                                if line_variant and line_variant.get("barcode") == barcode:
                                    remaining_qty = fo_line.get("remainingQuantity", 0)
                                    if remaining_qty > 0:
                                        older_orders.append({
                                            "order": order.get("name"),
                                            "created": order.get("createdAt"),
                                            "quantity": remaining_qty,
                                            "tags": order.get("tags", [])
                                        })
                
                page_info = orders_data.get("pageInfo", {})
                has_next_page = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")
            
            print(f"\nChecked {checked_orders} orders total")
            
            if older_orders:
                print(f"\nFound {len(older_orders)} older orders (> {days_back} days):")
                older_total = 0
                for order in older_orders[:10]:  # Show first 10
                    print(f"  - {order['order']} created {order['created']}: {order['quantity']} units")
                    older_total += order['quantity']
                if len(older_orders) > 10:
                    remaining_qty = sum(o['quantity'] for o in older_orders[10:])
                    print(f"  ... and {len(older_orders) - 10} more orders with {remaining_qty} units")
                    older_total += remaining_qty
                print(f"\nTotal from older orders: {older_total}")
                print(f"This accounts for {older_total} of the {committed_qty - total_quantity} difference")
            else:
                print(f"\nNo older orders found with barcode {barcode} at {location_alias}")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(diagnose_barcode_scc())