"""Test fraud analysis with Robert Atkins who has immediate previous order cancelled"""

import asyncio
import logging
from database import SessionLocal
from models import ShopifyStore, User, FraudAnalysis
from fraud_service import FraudAnalysisService
from enhanced_shopify_client import EnhancedShopifyClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_robert_atkins_order():
    """Test fraud analysis for Robert Atkins order PW110445"""
    
    db = SessionLocal()
    try:
        # Get store and user
        store = db.query(ShopifyStore).filter(ShopifyStore.is_active == True).first()
        if not store:
            logger.error("No active store found")
            return
        
        user = db.query(User).filter(User.id == store.user_id).first()
        if not user:
            logger.error("No user found for store")
            return
        
        logger.info(f"Testing with store: {store.shop_name}")
        
        # Test with Robert Atkins' order
        test_order = "PW110445"
        logger.info(f"Testing order: {test_order}")
        logger.info("Customer: Robert Atkins (immediate previous order PW17398 was cancelled)")
        
        client = EnhancedShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        # Get the full order data
        order_data = await client.get_order_with_comprehensive_delivery_data(test_order)
        
        if not order_data:
            logger.error(f"Failed to get order data for {test_order}")
            return
        
        # Check customer order history
        customer = order_data.get('customer', {})
        orders_history = customer.get('orders', {}).get('edges', [])
        
        logger.info(f"\nCustomer order history (first 5):")
        for i, order_edge in enumerate(orders_history[:5]):
            order = order_edge['node']
            logger.info(f"  {i+1}. {order['name']} - cancelledAt: {order.get('cancelledAt', 'None')}")
        
        # Create fraud analysis service
        fraud_service = FraudAnalysisService(db, store, user)
        
        # Test the specific method
        logger.info("\nTesting _check_previous_order_cancelled method...")
        prev_cancelled = fraud_service._check_previous_order_cancelled(order_data)
        logger.info(f"Result: {prev_cancelled}")
        
        if prev_cancelled is True:
            logger.info("✅ SUCCESS! The method correctly detected a previous cancelled order!")
        elif prev_cancelled is False:
            logger.warning("❌ The method returned False - no cancelled order detected")
        else:
            logger.warning("❌ The method returned None - no previous order found")
        
        # Run full fraud analysis
        logger.info("\nRunning full fraud analysis...")
        fraud_analysis = fraud_service.analyze_order_fraud(order_data)
        
        if fraud_analysis:
            logger.info(f"✅ Fraud analysis created with ID: {fraud_analysis.id}")
            logger.info(f"   previous_order_cancelled: {fraud_analysis.previous_order_cancelled}")
            
            # Verify it was saved to database
            saved_analysis = db.query(FraudAnalysis).filter(
                FraudAnalysis.id == fraud_analysis.id
            ).first()
            
            if saved_analysis:
                logger.info(f"✅ Database verification - previous_order_cancelled: {saved_analysis.previous_order_cancelled}")
                
                if saved_analysis.previous_order_cancelled is True:
                    logger.info("\n🎉 SUCCESS! The feature is working correctly!")
                    logger.info("   A customer with an immediately cancelled previous order was properly flagged.")
                else:
                    logger.error("\n❌ PROBLEM: The field was not set to True despite cancelled immediate previous order")
            
            # Clean up test data
            db.delete(fraud_analysis)
            db.commit()
            logger.info("\n(Test analysis deleted)")
        else:
            logger.error("Failed to create fraud analysis")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_robert_atkins_order())