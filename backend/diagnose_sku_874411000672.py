#!/usr/bin/env python3
"""
Simple diagnostic script to find all unfulfilled orders for SKU 874411000672
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import DATABASE_URL
from models import ShopifyStore
from shopify_client import ShopifyClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def diagnose_sku():
    sku = "874411000672"
    
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
            
        print(f"\n=== Finding all unfulfilled orders for SKU {sku} ===")
        print(f"Store: {store.shop_name}\n")
        
        # Create Shopify client
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        # Query to find all orders with this SKU
        orders_query = """
        query searchOrdersBySku($query: String!, $first: Int!, $after: String) {
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
                                                        sku
                                                        barcode
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
        
        # Search for unfulfilled orders with this SKU
        query_filter = f'(fulfillment_status:unshipped OR fulfillment_status:partial) AND NOT status:cancelled AND sku:"{sku}"'
        
        print(f"Query: {query_filter}")
        
        all_orders = []
        cursor = None
        has_next = True
        page = 0
        
        while has_next and page < 10:  # Limit to 10 pages
            page += 1
            variables = {
                "query": query_filter,
                "first": 20,
                "after": cursor
            }
            
            result = await client._make_graphql_request(orders_query, variables)
            orders_data = result.get("data", {}).get("orders", {})
            
            edges = orders_data.get("edges", [])
            print(f"\nPage {page}: Found {len(edges)} orders")
            
            for edge in edges:
                order = edge.get("node", {})
                order_name = order.get("name")
                order_created = order.get("createdAt")
                order_tags = order.get("tags", [])
                
                # Check all fulfillment orders
                fulfillment_orders = order.get("fulfillmentOrders", {}).get("edges", [])
                
                for fo_edge in fulfillment_orders:
                    fo = fo_edge.get("node", {})
                    location = fo.get("assignedLocation", {}).get("location", {})
                    location_name = location.get("name", "Unknown")
                    
                    # Check line items
                    line_items = fo.get("lineItems", {}).get("edges", [])
                    for line_edge in line_items:
                        line = line_edge.get("node", {})
                        variant = line.get("lineItem", {}).get("variant", {})
                        
                        if variant and variant.get("sku") == sku:
                            remaining_qty = line.get("remainingQuantity", 0)
                            if remaining_qty > 0:
                                all_orders.append({
                                    "order": order_name,
                                    "created": order_created,
                                    "quantity": remaining_qty,
                                    "location": location_name,
                                    "tags": order_tags
                                })
                                print(f"  - {order_name} at {location_name}: {remaining_qty} units")
            
            page_info = orders_data.get("pageInfo", {})
            has_next = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
        
        print(f"\n=== SUMMARY ===")
        print(f"Total orders with unfulfilled SKU {sku}: {len(all_orders)}")
        
        # Group by location
        by_location = {}
        for order in all_orders:
            loc = order["location"]
            if loc not in by_location:
                by_location[loc] = {"count": 0, "quantity": 0, "orders": []}
            by_location[loc]["count"] += 1
            by_location[loc]["quantity"] += order["quantity"]
            by_location[loc]["orders"].append(order)
        
        print(f"\nBy Location:")
        for location, data in by_location.items():
            print(f"\n{location}:")
            print(f"  Orders: {data['count']}")
            print(f"  Total quantity: {data['quantity']}")
            
            # Show recent orders
            recent = sorted(data["orders"], key=lambda x: x["created"], reverse=True)[:5]
            print(f"  Recent orders:")
            for order in recent:
                print(f"    - {order['order']} ({order['created'][:10]}): {order['quantity']} units")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(diagnose_sku())