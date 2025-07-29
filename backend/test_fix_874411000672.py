#!/usr/bin/env python3
"""
Test script to verify the fix for barcode 874411000672
"""
import asyncio
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import DATABASE_URL
from models import ShopifyStore, Settings, LocationMapping, LocationAlias
from shopify_client import ShopifyClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_fix():
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
            
        print(f"\n=== Testing fix for barcode {barcode} ===")
        print(f"Store: {store.shop_name}\n")
        
        # Get the location ID for SC
        alias = db.query(LocationAlias).filter(
            LocationAlias.user_id == store.user_id,
            LocationAlias.alias_name == location_alias,
            LocationAlias.is_active == True
        ).first()
        
        if not alias:
            print(f"Location alias {location_alias} not found!")
            return
            
        mapping = db.query(LocationMapping).filter(
            LocationMapping.alias_id == alias.id,
            LocationMapping.store_id == store.id,
            LocationMapping.is_active == True
        ).first()
        
        if not mapping:
            print(f"No mapping found for {location_alias} in store {store.shop_name}")
            return
            
        location_id = mapping.shopify_location_id
        print(f"Location: {location_alias} ({mapping.shopify_location_name})")
        print(f"Location ID: {location_id}")
        
        # Get user settings
        settings = db.query(Settings).filter(Settings.user_id == store.user_id).first()
        days_back = settings.inventory_verification_days_back if settings else 7
        excluded_tag = settings.inventory_verification_excluded_tag if settings else None
        
        print(f"\nSettings:")
        print(f"  Days back: {days_back}")
        print(f"  Excluded tag: {excluded_tag}")
        
        # Create Shopify client
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        # Call the updated verification method
        print(f"\nCalling get_unfulfilled_orders_for_verification...")
        result = await client.get_unfulfilled_orders_for_verification(
            barcode=barcode,
            days_back=days_back,
            excluded_tag=excluded_tag,
            location_id=location_id
        )
        
        print(f"\n=== RESULTS ===")
        print(f"Total quantity: {result.get('total_quantity', 0)}")
        print(f"Orders processed: {result.get('orders_processed', 0)}")
        print(f"Pages fetched: {result.get('pages_fetched', 0)}")
        print(f"Execution time: {result.get('execution_time', 0)}s")
        print(f"Hit time limit: {result.get('hit_time_limit', False)}")
        
        if result.get('error'):
            print(f"Error: {result.get('error')}")
        
        # Expected result: Should find all 3 orders (15 units total)
        print(f"\n✅ Expected: 15 units from 3 orders")
        print(f"{'✅' if result.get('total_quantity') == 15 else '❌'} Actual: {result.get('total_quantity')} units")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_fix())