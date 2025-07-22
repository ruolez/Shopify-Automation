#!/usr/bin/env python3
"""
Test script to verify the reconcile functionality for fraud detection
"""
import asyncio
import logging
import sys
from sqlalchemy.orm import Session
from database import SessionLocal
from models import User, ShopifyStore, FraudAnalysis
from shopify_client import ShopifyClient
from fraud_archive_service import FraudArchiveService

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_order_status_check(db: Session, user_id: int):
    """Test fetching order status from Shopify"""
    logger.info(f"Testing order status check for user {user_id}")
    
    # Get user's stores
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == user_id,
        ShopifyStore.is_active == True
    ).all()
    
    if not stores:
        logger.error("No active stores found for user")
        return
    
    store = stores[0]
    logger.info(f"Using store: {store.shop_name}")
    
    # Get a fraud analysis to test with
    analysis = db.query(FraudAnalysis).filter(
        FraudAnalysis.user_id == user_id
    ).first()
    
    if not analysis:
        logger.error("No fraud analyses found to test with")
        return
    
    logger.info(f"Testing with order: {analysis.order_name}")
    
    # Test getting order status
    client = ShopifyClient(store.shop_domain, store.access_token)
    archive_service = FraudArchiveService(db)
    
    try:
        order_status = await archive_service._get_order_status(client, analysis.order_name)
        
        if order_status:
            logger.info(f"Order status retrieved successfully:")
            logger.info(f"  Fulfillment Status: {order_status.get('displayFulfillmentStatus')}")
            logger.info(f"  Financial Status: {order_status.get('displayFinancialStatus')}")
            logger.info(f"  Cancelled At: {order_status.get('cancelledAt')}")
            logger.info(f"  Raw Status: {order_status.get('status')}")
        else:
            logger.error("Failed to retrieve order status")
            
    except Exception as e:
        logger.error(f"Error testing order status: {str(e)}", exc_info=True)

async def test_archive_process(db: Session, user_id: int):
    """Test the archive process for fulfilled/cancelled orders"""
    logger.info(f"Testing archive process for user {user_id}")
    
    # Count initial fraud analyses
    initial_count = db.query(FraudAnalysis).filter(
        FraudAnalysis.user_id == user_id
    ).count()
    
    logger.info(f"Initial fraud analyses count: {initial_count}")
    
    # Run archive process
    archive_service = FraudArchiveService(db)
    
    try:
        result = await archive_service.archive_fulfilled_and_cancelled_analyses(
            user_id=user_id,
            max_analyses=10  # Test with small batch
        )
        
        logger.info(f"Archive process completed:")
        logger.info(f"  Checked: {result['checked']}")
        logger.info(f"  Archived: {result['archived']}")
        logger.info(f"  Failed: {result['failed']}")
        logger.info(f"  Reasons: {result['reasons']}")
        logger.info(f"  Remaining: {result.get('total_remaining', 0)}")
        
        if result['archived_orders']:
            logger.info("Archived orders:")
            for order in result['archived_orders']:
                logger.info(f"  - {order['order_name']} ({order['archive_reason']})")
        
        # Verify counts
        final_count = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id
        ).count()
        
        logger.info(f"Final fraud analyses count: {final_count}")
        logger.info(f"Difference: {initial_count - final_count} (should match archived count)")
        
    except Exception as e:
        logger.error(f"Error testing archive process: {str(e)}", exc_info=True)

async def main():
    """Main test function"""
    if len(sys.argv) < 2:
        print("Usage: python test_reconcile_fix.py <user_id>")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Verify user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return
        
        logger.info(f"Testing reconcile functionality for user: {user.email}")
        
        # Test 1: Order status check
        logger.info("\n=== TEST 1: Order Status Check ===")
        await test_order_status_check(db, user_id)
        
        # Test 2: Archive process
        logger.info("\n=== TEST 2: Archive Process ===")
        await test_archive_process(db, user_id)
        
        logger.info("\nAll tests completed!")
        
    except Exception as e:
        logger.error(f"Test failed: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())