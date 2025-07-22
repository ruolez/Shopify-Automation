#!/usr/bin/env python3
"""
Test archiving of a specific order
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

async def test_specific_order(db: Session, order_name: str):
    """Test archiving a specific order"""
    logger.info(f"Testing archive for order: {order_name}")
    
    # Find the fraud analysis for this order
    analysis = db.query(FraudAnalysis).filter(
        FraudAnalysis.order_name == order_name
    ).first()
    
    if not analysis:
        logger.error(f"No fraud analysis found for order {order_name}")
        return
    
    logger.info(f"Found fraud analysis ID {analysis.id} for order {order_name}")
    logger.info(f"  User ID: {analysis.user_id}")
    logger.info(f"  Store ID: {analysis.store_id}")
    logger.info(f"  Customer: {analysis.customer_name}")
    logger.info(f"  Created: {analysis.analysis_timestamp}")
    
    # Get the store
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == analysis.store_id
    ).first()
    
    if not store:
        logger.error(f"Store {analysis.store_id} not found")
        return
    
    logger.info(f"Using store: {store.shop_name}")
    
    # Test getting order status
    client = ShopifyClient(store.shop_domain, store.access_token)
    archive_service = FraudArchiveService(db)
    
    try:
        # Get order status
        logger.info("Fetching order status from Shopify...")
        order_status = await archive_service._get_order_status(client, order_name)
        
        if order_status:
            logger.info(f"Order status retrieved:")
            logger.info(f"  Fulfillment Status: {order_status.get('displayFulfillmentStatus')}")
            logger.info(f"  Financial Status: {order_status.get('displayFinancialStatus')}")
            logger.info(f"  Cancelled At: {order_status.get('cancelledAt')}")
            
            # Check if it should be archived
            fulfillment_status = order_status.get('displayFulfillmentStatus')
            if fulfillment_status and fulfillment_status.upper() == 'FULFILLED':
                logger.info("Order is FULFILLED - should be archived")
                
                # Try to archive it manually
                logger.info("Attempting to archive the order...")
                success = archive_service._archive_analysis(analysis, "order_fulfilled")
                
                if success:
                    db.commit()
                    logger.info("✅ Order successfully archived!")
                    
                    # Verify it's gone from active table
                    check = db.query(FraudAnalysis).filter(
                        FraudAnalysis.id == analysis.id
                    ).first()
                    
                    if check is None:
                        logger.info("✅ Confirmed: Order removed from active fraud analyses")
                    else:
                        logger.error("❌ ERROR: Order still exists in active table!")
                else:
                    logger.error("❌ Failed to archive the order")
            else:
                logger.info(f"Order status is '{fulfillment_status}' - not eligible for archiving")
        else:
            logger.error("Failed to retrieve order status from Shopify")
            
    except Exception as e:
        logger.error(f"Error testing order archive: {str(e)}", exc_info=True)

async def main():
    """Main test function"""
    if len(sys.argv) < 2:
        print("Usage: python test_specific_order_archive.py <order_name>")
        print("Example: python test_specific_order_archive.py TS8306384")
        sys.exit(1)
    
    order_name = sys.argv[1]
    
    # Create database session
    db = SessionLocal()
    
    try:
        await test_specific_order(db, order_name)
    except Exception as e:
        logger.error(f"Test failed: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())