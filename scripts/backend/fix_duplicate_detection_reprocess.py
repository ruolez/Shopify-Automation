#!/usr/bin/env python3
"""Fix duplicate detection in fraud rule reprocessing by ensuring proper user context"""

import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from database import SessionLocal
from models import User, ShopifyStore, Settings, FraudAnalysis
from shopify_client import ShopifyClient
from fraud_service import FraudAnalysisService
from fraud_rule_processor import process_fraud_rules_for_order_async
import asyncio
import pytz

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def fix_duplicate_detection_for_user(user_id: int, days_back: int = 7):
    """Fix duplicate detection for all recent fraud analyses for a user"""
    
    db = SessionLocal()
    try:
        # Get user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return
        
        # Get user settings
        user_settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        if user_settings:
            logger.info(f"User settings found:")
            logger.info(f"  - duplicate_detection_days: {user_settings.duplicate_detection_days}")
            logger.info(f"  - timezone: {user_settings.timezone}")
        else:
            logger.warning("No user settings found")
        
        # Calculate date range
        user_timezone = user_settings.timezone if user_settings and user_settings.timezone else "UTC"
        user_tz = pytz.timezone(user_timezone)
        now_user_tz = datetime.now(user_tz)
        since_date_user_tz = now_user_tz - timedelta(days=days_back)
        since_date = since_date_user_tz.astimezone(timezone.utc)
        
        # Get recent fraud analyses
        fraud_analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.analysis_timestamp >= since_date
        ).all()
        
        logger.info(f"\nFound {len(fraud_analyses)} fraud analyses from last {days_back} days")
        
        updated_count = 0
        failed_count = 0
        
        for analysis in fraud_analyses:
            try:
                logger.info(f"\nProcessing order: {analysis.order_name}")
                logger.info(f"  Current duplicate_within_7days: {analysis.duplicate_within_7days}")
                
                # Get the store
                store = db.query(ShopifyStore).filter(
                    ShopifyStore.id == analysis.store_id
                ).first()
                
                if not store:
                    logger.warning(f"  Store {analysis.store_id} not found")
                    failed_count += 1
                    continue
                
                # Get order data from Shopify
                client = ShopifyClient(store.shop_domain, store.access_token)
                order_id = analysis.shopify_order_id
                if not order_id.startswith('gid://'):
                    order_id = f"gid://shopify/Order/{order_id}"
                
                order_data = await client.get_order_by_id(order_id)
                
                if not order_data:
                    logger.warning(f"  Could not fetch order data for {order_id}")
                    failed_count += 1
                    continue
                
                # Create fraud service with correct user context
                fraud_service = FraudAnalysisService(db, store, user)
                
                # Recalculate duplicate detection
                new_duplicate_value = fraud_service._check_duplicate_within_configurable_days(order_data)
                
                if new_duplicate_value != analysis.duplicate_within_7days:
                    logger.info(f"  ✓ Updating duplicate detection: {analysis.duplicate_within_7days} -> {new_duplicate_value}")
                    analysis.duplicate_within_7days = new_duplicate_value
                    db.commit()
                    updated_count += 1
                    
                    # Verify the update
                    db.refresh(analysis)
                    if analysis.duplicate_within_7days == new_duplicate_value:
                        logger.info(f"  ✓ Update verified: {analysis.duplicate_within_7days}")
                    else:
                        logger.error(f"  ✗ Update failed! Still shows: {analysis.duplicate_within_7days}")
                else:
                    logger.info(f"  - No change needed (already {new_duplicate_value})")
                
                # Also reprocess fraud rules for this order
                logger.info(f"  Reprocessing fraud rules...")
                fraud_results = await process_fraud_rules_for_order_async(
                    db, user, store, order_data, analysis
                )
                
                if fraud_results:
                    logger.info(f"  ✓ Fraud rules processed: {fraud_results.get('rules_matched', 0)} rules matched")
                else:
                    logger.warning(f"  ⚠ Fraud rule processing returned no results")
                
            except Exception as e:
                logger.error(f"  ✗ Error processing order {analysis.order_name}: {str(e)}")
                failed_count += 1
                continue
        
        logger.info(f"\n=== SUMMARY ===")
        logger.info(f"Total analyses: {len(fraud_analyses)}")
        logger.info(f"Updated: {updated_count}")
        logger.info(f"Failed: {failed_count}")
        logger.info(f"Unchanged: {len(fraud_analyses) - updated_count - failed_count}")
        
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
    finally:
        db.close()

async def fix_single_order(user_id: int, order_name: str):
    """Fix duplicate detection for a specific order"""
    
    db = SessionLocal()
    try:
        # Get user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return
        
        # Get fraud analysis
        analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.order_name == order_name
        ).first()
        
        if not analysis:
            logger.error(f"No fraud analysis found for order {order_name}")
            return
        
        logger.info(f"\n=== Fixing duplicate detection for order {order_name} ===")
        logger.info(f"Current duplicate_within_7days: {analysis.duplicate_within_7days}")
        
        # Get store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == analysis.store_id
        ).first()
        
        if not store:
            logger.error(f"Store {analysis.store_id} not found")
            return
        
        # Get user settings to show current configuration
        user_settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        if user_settings:
            logger.info(f"User duplicate_detection_days setting: {user_settings.duplicate_detection_days}")
        
        # Get order data
        client = ShopifyClient(store.shop_domain, store.access_token)
        order_id = analysis.shopify_order_id
        if not order_id.startswith('gid://'):
            order_id = f"gid://shopify/Order/{order_id}"
        
        order_data = await client.get_order_by_id(order_id)
        
        if not order_data:
            logger.error("Could not fetch order data")
            return
        
        # Create fraud service with correct user context
        fraud_service = FraudAnalysisService(db, store, user)
        
        # Calculate new value
        new_value = fraud_service._check_duplicate_within_configurable_days(order_data)
        logger.info(f"Calculated new duplicate value: {new_value}")
        
        if new_value != analysis.duplicate_within_7days:
            # Update the value
            analysis.duplicate_within_7days = new_value
            db.commit()
            logger.info(f"✓ Updated duplicate_within_7days to {new_value}")
            
            # Verify
            db.refresh(analysis)
            logger.info(f"Verification: duplicate_within_7days = {analysis.duplicate_within_7days}")
            
            # Reprocess fraud rules
            logger.info("\nReprocessing fraud rules with updated data...")
            fraud_results = await process_fraud_rules_for_order_async(
                db, user, store, order_data, analysis
            )
            
            if fraud_results:
                logger.info(f"✓ Fraud rules processed successfully")
                logger.info(f"  Rules matched: {fraud_results.get('rules_matched', 0)}")
                logger.info(f"  Actions executed: {fraud_results.get('actions_executed', 0)}")
        else:
            logger.info(f"No update needed - value is already {new_value}")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Fix all recent: python fix_duplicate_detection_reprocess.py <user_id> [days_back]")
        print("  Fix single order: python fix_duplicate_detection_reprocess.py <user_id> --order <order_name>")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    
    if len(sys.argv) >= 4 and sys.argv[2] == "--order":
        # Fix single order
        order_name = sys.argv[3]
        asyncio.run(fix_single_order(user_id, order_name))
    else:
        # Fix all recent
        days_back = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        asyncio.run(fix_duplicate_detection_for_user(user_id, days_back))