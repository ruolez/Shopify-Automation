#!/usr/bin/env python3
"""Debug duplicate detection issues during fraud rule reprocessing"""

import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from database import SessionLocal
from models import User, ShopifyStore, Settings, FraudAnalysis
from shopify_client import ShopifyClient
from fraud_service import FraudAnalysisService
import asyncio
import json

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def debug_duplicate_detection(user_id: int, order_name: str = None):
    """Debug duplicate detection calculation issues"""
    db = SessionLocal()
    
    try:
        # Get user and settings
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return
            
        user_settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        duplicate_detection_days = user_settings.duplicate_detection_days if user_settings else 7
        
        logger.info(f"=== DUPLICATE DETECTION DEBUG FOR USER {user_id} ===")
        logger.info(f"Current duplicate_detection_days setting: {duplicate_detection_days}")
        
        # Get recent fraud analyses
        query = db.query(FraudAnalysis).filter(FraudAnalysis.user_id == user_id)
        if order_name:
            query = query.filter(FraudAnalysis.order_name == order_name)
        else:
            # Get recent analyses from last 7 days
            since_date = datetime.now(timezone.utc) - timedelta(days=7)
            query = query.filter(FraudAnalysis.analysis_timestamp >= since_date)
        
        analyses = query.limit(10).all()
        
        logger.info(f"Found {len(analyses)} fraud analyses to check")
        
        for analysis in analyses:
            logger.info(f"\n--- Checking Order: {analysis.order_name} ---")
            logger.info(f"Current duplicate_within_7days value: {analysis.duplicate_within_7days}")
            logger.info(f"Analysis timestamp: {analysis.analysis_timestamp}")
            
            # Get the store
            store = db.query(ShopifyStore).filter(ShopifyStore.id == analysis.store_id).first()
            if not store:
                logger.error(f"Store {analysis.store_id} not found")
                continue
            
            # Get fresh order data from Shopify
            client = ShopifyClient(store.shop_domain, store.access_token)
            order_id = analysis.shopify_order_id
            if not order_id.startswith('gid://'):
                order_id = f"gid://shopify/Order/{order_id}"
            
            logger.info(f"Fetching order {order_id} from Shopify...")
            order_data = await client.get_order_by_id(order_id)
            
            if not order_data:
                logger.error(f"Could not fetch order data for {order_id}")
                continue
            
            # Debug the order data structure
            logger.debug(f"Order data keys: {list(order_data.keys())[:10]}")
            
            # Check customer data
            customer = order_data.get('customer', {})
            if not customer:
                logger.warning("No customer data in order")
                continue
                
            # Check customer orders
            customer_orders = customer.get('orders', {}).get('edges', [])
            logger.info(f"Customer has {len(customer_orders)} orders in history")
            
            # Get current order creation date
            created_at_str = order_data.get('createdAt', '')
            current_order_id = order_data.get('id', '')
            
            if not created_at_str:
                logger.error("No creation date for current order")
                continue
                
            created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            detection_period_ago = created_at - timedelta(days=duplicate_detection_days)
            
            logger.info(f"Current order created at: {created_at}")
            logger.info(f"Detection period starts: {detection_period_ago}")
            logger.info(f"Looking for duplicates between {detection_period_ago} and {created_at}")
            
            # Check for duplicates manually
            duplicate_count = 0
            duplicate_orders = []
            
            for i, order_edge in enumerate(customer_orders):
                order = order_edge['node']
                order_name_check = order.get('name', 'Unknown')
                order_created_str = order.get('createdAt', '')
                order_id_check = order.get('id', '')
                
                if order_created_str and order_id_check != current_order_id:
                    order_created = datetime.fromisoformat(order_created_str.replace('Z', '+00:00'))
                    
                    # Log all orders for debugging
                    days_diff = (created_at - order_created).days
                    logger.debug(f"  Order {i+1}: {order_name_check} created {order_created} ({days_diff} days before current)")
                    
                    if detection_period_ago <= order_created <= created_at:
                        duplicate_count += 1
                        duplicate_orders.append({
                            'name': order_name_check,
                            'created': order_created,
                            'days_before': days_diff
                        })
                        logger.info(f"  ✓ DUPLICATE FOUND: {order_name_check} ({days_diff} days before)")
                    elif order_created > created_at:
                        logger.warning(f"  ⚠️ Order {order_name_check} created AFTER current order? {order_created}")
            
            logger.info(f"Manual duplicate count: {duplicate_count}")
            logger.info(f"Duplicate orders found: {duplicate_orders}")
            
            # Now use the fraud service to calculate
            fraud_service = FraudAnalysisService(db, store, user)
            
            # Test the method directly
            logger.info("\nTesting fraud service duplicate detection...")
            calculated_duplicate = fraud_service._check_duplicate_within_configurable_days(order_data)
            logger.info(f"Fraud service calculated duplicate: {calculated_duplicate}")
            
            # Compare with stored value
            if analysis.duplicate_within_7days != calculated_duplicate:
                logger.warning(f"❌ MISMATCH: Stored={analysis.duplicate_within_7days}, Calculated={calculated_duplicate}")
                
                # Try updating the value
                logger.info("Attempting to update the stored value...")
                analysis.duplicate_within_7days = calculated_duplicate
                db.commit()
                logger.info(f"✓ Updated duplicate_within_7days to {calculated_duplicate}")
                
                # Verify the update
                db.refresh(analysis)
                logger.info(f"Verification: New stored value = {analysis.duplicate_within_7days}")
            else:
                logger.info(f"✓ Values match: {analysis.duplicate_within_7days}")
            
            # Additional debug: Check if the fraud_service is using correct user settings
            logger.info(f"\nDebug fraud_service internals:")
            logger.info(f"  fraud_service.user.id = {fraud_service.user.id}")
            logger.info(f"  fraud_service.store.id = {fraud_service.store.id}")
            
            # Check settings directly within fraud service context
            settings_check = fraud_service.db.query(Settings).filter(Settings.user_id == fraud_service.user.id).first()
            logger.info(f"  Settings check: duplicate_detection_days = {settings_check.duplicate_detection_days if settings_check else 'No settings'}")
            
    except Exception as e:
        logger.error(f"Error in debug: {str(e)}", exc_info=True)
    finally:
        db.close()

async def test_reprocess_simulation(user_id: int, order_name: str):
    """Simulate the reprocess_fraud_rules_recent behavior for a specific order"""
    db = SessionLocal()
    
    try:
        logger.info(f"\n=== SIMULATING REPROCESS FOR ORDER {order_name} ===")
        
        # Get the fraud analysis
        analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.order_name == order_name
        ).first()
        
        if not analysis:
            logger.error(f"No fraud analysis found for order {order_name}")
            return
            
        logger.info(f"Found fraud analysis ID: {analysis.id}")
        logger.info(f"Current duplicate_within_7days: {analysis.duplicate_within_7days}")
        
        # Get user and store
        user = db.query(User).filter(User.id == user_id).first()
        store = db.query(ShopifyStore).filter(ShopifyStore.id == analysis.store_id).first()
        
        if not user or not store:
            logger.error("User or store not found")
            return
            
        # Get order data
        client = ShopifyClient(store.shop_domain, store.access_token)
        order_id = analysis.shopify_order_id
        if not order_id.startswith('gid://'):
            order_id = f"gid://shopify/Order/{order_id}"
            
        order_data = await client.get_order_by_id(order_id)
        
        if not order_data:
            logger.error("Could not fetch order data")
            return
            
        # Create fraud service and update duplicate detection
        logger.info("\nCreating fraud service and updating duplicate detection...")
        fraud_service = FraudAnalysisService(db, store, user)
        
        try:
            updated_duplicate = fraud_service._check_duplicate_within_configurable_days(order_data)
            logger.info(f"New duplicate value calculated: {updated_duplicate}")
            
            # Update the analysis
            analysis.duplicate_within_7days = updated_duplicate
            db.commit()
            logger.info(f"✓ Successfully updated duplicate_within_7days to {updated_duplicate}")
            
            # Verify
            db.refresh(analysis)
            logger.info(f"Verification: Stored value is now {analysis.duplicate_within_7days}")
            
        except Exception as e:
            logger.error(f"Failed to update duplicate detection: {str(e)}", exc_info=True)
            db.rollback()
            
    except Exception as e:
        logger.error(f"Error in simulation: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python debug_duplicate_detection.py <user_id> [order_name]")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    order_name = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Run debug
    asyncio.run(debug_duplicate_detection(user_id, order_name))
    
    # If specific order provided, also run simulation
    if order_name:
        asyncio.run(test_reprocess_simulation(user_id, order_name))