#!/usr/bin/env python3
"""
Check the latest order from Shopify and compare with fraud analyses
"""

import sys
import os
import asyncio
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import User, ShopifyStore, Settings, FraudAnalysis
from shopify_client import ShopifyClient
from sqlalchemy import desc

async def check_latest_orders():
    db = SessionLocal()
    try:
        # Get primewholesale store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == "primewholesale-com.myshopify.com",
            ShopifyStore.is_active == True
        ).first()
        
        if not store:
            print("Store not found!")
            return
        
        print(f"Checking store: {store.shop_name} ({store.shop_domain})")
        print(f"Store ID: {store.id}")
        print(f"Last sync: {store.last_sync}")
        
        # Get settings
        settings = db.query(Settings).filter(Settings.user_id == store.user_id).first()
        if settings:
            print(f"Sync window: {settings.sync_window_days} days")
        
        # Initialize Shopify client
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        # Fetch most recent orders
        print("\nFetching latest orders from Shopify...")
        orders_data = await client.get_orders(
            limit=10,
            created_at_min=(datetime.utcnow() - timedelta(days=1)).isoformat()
        )
        
        if orders_data and "edges" in orders_data:
            edges = orders_data["edges"]
            print(f"Found {len(edges)} orders in last 24 hours")
            
            for edge in edges[:5]:  # Show first 5
                order = edge["node"]
                order_name = order.get("name", "Unknown")
                order_id = order.get("id", "Unknown")
                created_at = order.get("createdAt", "Unknown")
                
                print(f"\nOrder: {order_name}")
                print(f"  ID: {order_id}")
                print(f"  Created: {created_at}")
                
                # Check if fraud analysis exists
                fraud_analysis = db.query(FraudAnalysis).filter(
                    FraudAnalysis.order_name == order_name,
                    FraudAnalysis.store_id == store.id
                ).first()
                
                if fraud_analysis:
                    print(f"  ✅ Fraud analysis exists (analyzed at: {fraud_analysis.analysis_timestamp})")
                else:
                    print(f"  ❌ NO FRAUD ANALYSIS FOUND!")
        else:
            print("No orders found in response")
            
        # Also check the latest fraud analysis
        print("\n" + "="*60)
        print("Latest fraud analyses in database:")
        latest_frauds = db.query(FraudAnalysis).filter(
            FraudAnalysis.store_id == store.id
        ).order_by(desc(FraudAnalysis.analysis_timestamp)).limit(5).all()
        
        for fraud in latest_frauds:
            print(f"  - {fraud.order_name}: analyzed at {fraud.analysis_timestamp}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(check_latest_orders())