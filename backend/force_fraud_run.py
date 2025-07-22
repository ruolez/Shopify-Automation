#!/usr/bin/env python3
"""
Force a fraud detection run for the store.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tasks import process_store_fraud_detection
from database import SessionLocal
from models import ShopifyStore
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def force_fraud_run():
    """Force fraud detection for the store."""
    db = SessionLocal()
    
    try:
        # Get the store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == "fff517-2.myshopify.com"
        ).first()
        
        if not store:
            logger.error("Store not found")
            return
            
        logger.info(f"Triggering fraud detection for store ID {store.id}")
        
        # Call the task directly
        result = process_store_fraud_detection(store.id)
        logger.info(f"Result: {result}")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    force_fraud_run()