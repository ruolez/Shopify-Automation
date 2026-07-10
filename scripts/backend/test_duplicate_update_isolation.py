#!/usr/bin/env python3
"""Test duplicate detection update in isolation to identify transaction/caching issues"""

import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from database import SessionLocal, engine
from models import User, ShopifyStore, Settings, FraudAnalysis
from shopify_client import ShopifyClient
from fraud_service import FraudAnalysisService
import asyncio

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_duplicate_update_isolation(user_id: int, order_name: str):
    """Test updating duplicate detection in complete isolation"""
    
    logger.info(f"\n=== ISOLATED DUPLICATE DETECTION UPDATE TEST ===")
    logger.info(f"User ID: {user_id}, Order: {order_name}")
    
    # Test 1: Direct database update
    logger.info("\n--- Test 1: Direct Database Update ---")
    db1 = SessionLocal()
    try:
        analysis = db1.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.order_name == order_name
        ).first()
        
        if not analysis:
            logger.error(f"No fraud analysis found for order {order_name}")
            return
            
        logger.info(f"Current duplicate_within_7days: {analysis.duplicate_within_7days}")
        
        # Try direct update
        new_value = not analysis.duplicate_within_7days
        analysis.duplicate_within_7days = new_value
        db1.commit()
        logger.info(f"✓ Updated to {new_value} and committed")
        
        # Verify in same session
        db1.refresh(analysis)
        logger.info(f"Same session verification: {analysis.duplicate_within_7days}")
        
    except Exception as e:
        logger.error(f"Test 1 failed: {str(e)}", exc_info=True)
        db1.rollback()
    finally:
        db1.close()
    
    # Test 2: Verify in new session
    logger.info("\n--- Test 2: Verify in New Session ---")
    db2 = SessionLocal()
    try:
        analysis2 = db2.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.order_name == order_name
        ).first()
        
        logger.info(f"New session value: {analysis2.duplicate_within_7days}")
        
    except Exception as e:
        logger.error(f"Test 2 failed: {str(e)}")
    finally:
        db2.close()
    
    # Test 3: Test with fraud service calculation
    logger.info("\n--- Test 3: Fraud Service Calculation ---")
    db3 = SessionLocal()
    try:
        # Get required data
        user = db3.query(User).filter(User.id == user_id).first()
        analysis = db3.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.order_name == order_name
        ).first()
        store = db3.query(ShopifyStore).filter(ShopifyStore.id == analysis.store_id).first()
        
        # Get user settings
        settings = db3.query(Settings).filter(Settings.user_id == user_id).first()
        logger.info(f"User settings - duplicate_detection_days: {settings.duplicate_detection_days if settings else 'No settings'}")
        
        # Get order data
        client = ShopifyClient(store.shop_domain, store.access_token)
        order_id = analysis.shopify_order_id
        if not order_id.startswith('gid://'):
            order_id = f"gid://shopify/Order/{order_id}"
            
        order_data = await client.get_order_by_id(order_id)
        
        if order_data:
            # Create fraud service
            fraud_service = FraudAnalysisService(db3, store, user)
            
            # Calculate duplicate
            calculated = fraud_service._check_duplicate_within_configurable_days(order_data)
            logger.info(f"Calculated duplicate value: {calculated}")
            
            # Update
            analysis.duplicate_within_7days = calculated
            db3.commit()
            logger.info(f"✓ Updated to calculated value {calculated}")
            
            # Verify
            db3.refresh(analysis)
            logger.info(f"Post-update verification: {analysis.duplicate_within_7days}")
            
    except Exception as e:
        logger.error(f"Test 3 failed: {str(e)}", exc_info=True)
        db3.rollback()
    finally:
        db3.close()
    
    # Test 4: Check if there are any database constraints
    logger.info("\n--- Test 4: Database Schema Check ---")
    db4 = SessionLocal()
    try:
        # Check column type and constraints
        from sqlalchemy import inspect
        inspector = inspect(engine)
        columns = inspector.get_columns('fraud_analyses')
        
        for col in columns:
            if col['name'] == 'duplicate_within_7days':
                logger.info(f"Column info: {col}")
                
        # Try raw SQL update
        result = db4.execute(
            "UPDATE fraud_analyses SET duplicate_within_7days = ? WHERE user_id = ? AND order_name = ?",
            [True, user_id, order_name]
        )
        db4.commit()
        logger.info(f"✓ Raw SQL update affected {result.rowcount} rows")
        
        # Verify with raw SQL
        result = db4.execute(
            "SELECT duplicate_within_7days FROM fraud_analyses WHERE user_id = ? AND order_name = ?",
            [user_id, order_name]
        ).fetchone()
        logger.info(f"Raw SQL verification: {result[0] if result else 'Not found'}")
        
    except Exception as e:
        logger.error(f"Test 4 failed: {str(e)}", exc_info=True)
        db4.rollback()
    finally:
        db4.close()
    
    # Test 5: Test the full reprocess flow
    logger.info("\n--- Test 5: Full Reprocess Flow Simulation ---")
    db5 = SessionLocal()
    try:
        # Simulate the exact flow from reprocess_fraud_rules_recent
        user = db5.query(User).filter(User.id == user_id).first()
        analysis = db5.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.order_name == order_name
        ).first()
        store = db5.query(ShopifyStore).filter(ShopifyStore.id == analysis.store_id).first()
        
        logger.info(f"Before reprocess: duplicate_within_7days = {analysis.duplicate_within_7days}")
        
        # Get order data
        client = ShopifyClient(store.shop_domain, store.access_token)
        order_id = analysis.shopify_order_id
        if not order_id.startswith('gid://'):
            order_id = f"gid://shopify/Order/{order_id}"
            
        order_data = await client.get_order_by_id(order_id)
        
        if order_data:
            # This is the exact code from reprocess_fraud_rules_recent
            logger.info(f"Re-calculating duplicate detection for order {analysis.order_name}")
            fraud_service = FraudAnalysisService(db5, store, user)
            
            try:
                updated_duplicate = fraud_service._check_duplicate_within_configurable_days(order_data)
                analysis.duplicate_within_7days = updated_duplicate
                db5.commit()
                logger.info(f"Updated duplicate detection for order {analysis.order_name}: {updated_duplicate}")
            except Exception as e:
                logger.warning(f"Failed to update duplicate detection for order {analysis.order_name}: {str(e)}")
            
            # Final verification
            db5.refresh(analysis)
            logger.info(f"Final verification: duplicate_within_7days = {analysis.duplicate_within_7days}")
            
    except Exception as e:
        logger.error(f"Test 5 failed: {str(e)}", exc_info=True)
        db5.rollback()
    finally:
        db5.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 3:
        print("Usage: python test_duplicate_update_isolation.py <user_id> <order_name>")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    order_name = sys.argv[2]
    
    asyncio.run(test_duplicate_update_isolation(user_id, order_name))