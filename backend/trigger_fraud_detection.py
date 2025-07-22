#!/usr/bin/env python3
"""
Manually trigger fraud detection for a specific store
"""

import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import ShopifyStore
from tasks import process_store_fraud_detection

def trigger_fraud_detection():
    db = SessionLocal()
    try:
        # Get primewholesale store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == "primewholesale-com.myshopify.com"
        ).first()
        
        if not store:
            print("Store not found!")
            return
            
        print(f"Triggering fraud detection for store: {store.shop_name}")
        print(f"Store ID: {store.id}")
        print(f"User ID: {store.user_id}")
        
        # Trigger the task
        result = process_store_fraud_detection.apply_async(
            args=[store.user_id, store.id]
        )
        
        print(f"Task queued with ID: {result.id}")
        print("Check worker logs to monitor progress")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    trigger_fraud_detection()