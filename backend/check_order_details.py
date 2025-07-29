#!/usr/bin/env python3
"""
Check specific order details
"""
import asyncio
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import DATABASE_URL
from models import ShopifyStore
from shopify_client import ShopifyClient

async def check_orders():
    orders_to_check = ["TG55497", "TG55239", "TG55052"]
    
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        store = db.query(ShopifyStore).filter(
            ShopifyStore.is_active == True
        ).first()
        
        if not store:
            print("No active store found!")
            return
            
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        for order_name in orders_to_check:
            query = f"""
            query getOrder {{
                orders(first: 1, query: "name:{order_name}") {{
                    edges {{
                        node {{
                            name
                            createdAt
                            tags
                            displayFulfillmentStatus
                        }}
                    }}
                }}
            }}
            """
            
            result = await client._make_graphql_request(query, {})
            edges = result.get("data", {}).get("orders", {}).get("edges", [])
            
            if edges:
                order = edges[0].get("node", {})
                print(f"\nOrder: {order.get('name')}")
                print(f"Created: {order.get('createdAt')}")
                print(f"Status: {order.get('displayFulfillmentStatus')}")
                print(f"Tags: {order.get('tags', [])}")
            else:
                print(f"\nOrder {order_name} not found")
                
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(check_orders())