#!/usr/bin/env python3
"""
Trigger fraud detection for a specific order to test the customer_total_orders rule.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import asyncio
from sqlalchemy.orm import Session
from database import SessionLocal
from models import User, ShopifyStore
from fraud_service import FraudAnalysisService
from shopify_client import ShopifyClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def trigger_fraud_analysis():
    """Trigger fraud analysis for order TG54608."""
    db = SessionLocal()
    
    try:
        # Get the store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == "fff517-2.myshopify.com"
        ).first()
        
        if not store:
            logger.error("Store not found")
            return
            
        # Get the user
        user = db.query(User).filter(User.id == store.user_id).first()
        
        if not user:
            logger.error("User not found")
            return
            
        logger.info(f"Testing fraud detection for store: {store.shop_domain}")
        
        # Create clients
        shopify_client = ShopifyClient(store.shop_domain, store.access_token)
        fraud_service = FraudAnalysisService(db, store, user)
        
        # Get the specific order
        logger.info("Fetching order TG54608...")
        orders = await shopify_client.get_orders(limit=125)
        
        # Find the specific order
        target_order = None
        for order in orders:
            if order.get('name') == 'TG54608':
                target_order = order
                break
                
        if not target_order:
            logger.error("Order TG54608 not found")
            return
            
        logger.info("Running fraud analysis...")
        result = await fraud_service.analyze_order(target_order, force_reanalyze=True)
        
        if result:
            logger.info(f"Fraud analysis completed: {result}")
        else:
            logger.error("Fraud analysis failed")
            
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(trigger_fraud_analysis())