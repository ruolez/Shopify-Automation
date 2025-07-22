"""Debug the previous order logic to understand why it's not detecting cancelled orders"""

import asyncio
import logging
from database import SessionLocal
from models import ShopifyStore, User
from fraud_service import FraudAnalysisService
from enhanced_shopify_client import EnhancedShopifyClient

logging.basicConfig(level=logging.DEBUG)  # Set to DEBUG for more detail
logger = logging.getLogger(__name__)

async def debug_previous_order_logic():
    """Debug why previous_order_cancelled isn't working"""
    
    db = SessionLocal()
    try:
        store = db.query(ShopifyStore).filter(ShopifyStore.is_active == True).first()
        if not store:
            logger.error("No active store found")
            return
        
        user = db.query(User).filter(User.id == store.user_id).first()
        if not user:
            logger.error("No user found for store")
            return
        
        logger.info(f"Testing with store: {store.shop_name}")
        
        client = EnhancedShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        # Test with a specific order - let's find an order from a customer who has a cancelled order
        # From previous debugging, we know John Kelley has order PW19925 cancelled
        test_order = "PW110573"  # John Kelley's recent order
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing order: {test_order}")
        logger.info("Customer: John Kelley (has cancelled order PW19925)")
        logger.info("="*60)
        
        # Get the full order data
        order_data = await client.get_order_with_comprehensive_delivery_data(test_order)
        
        if not order_data:
            logger.error(f"Failed to get order data for {test_order}")
            return
        
        # Check the customer data structure
        customer = order_data.get('customer', {})
        logger.info(f"\nCustomer data found: {bool(customer)}")
        logger.info(f"Customer has {customer.get('numberOfOrders', 0)} total orders")
        
        # Check order history
        customer_orders = customer.get('orders', {}).get('edges', [])
        logger.info(f"Customer order history contains {len(customer_orders)} orders")
        
        # Log all orders in history with their cancelled status
        logger.info("\nCustomer order history:")
        for i, order_edge in enumerate(customer_orders):
            order = order_edge['node']
            logger.info(f"  {i+1}. {order['name']} - created: {order.get('createdAt', 'Unknown')} - cancelledAt: {order.get('cancelledAt', 'None')}")
        
        # Create fraud service and test the method
        fraud_service = FraudAnalysisService(db, store, user)
        
        # Test _get_previous_order_data
        logger.info("\n" + "="*60)
        logger.info("Testing _get_previous_order_data method...")
        status, total, prev_order = fraud_service._get_previous_order_data(order_data)
        
        if prev_order:
            logger.info(f"\nPrevious order found: {prev_order.get('name')}")
            logger.info(f"Previous order cancelledAt: {prev_order.get('cancelledAt')}")
            logger.info(f"Previous order created: {prev_order.get('createdAt')}")
        else:
            logger.warning("No previous order found!")
        
        # Test _check_previous_order_cancelled
        logger.info("\n" + "="*60)
        logger.info("Testing _check_previous_order_cancelled method...")
        prev_cancelled = fraud_service._check_previous_order_cancelled(order_data)
        
        logger.info(f"\nResult: {prev_cancelled}")
        logger.info(f"Type: {type(prev_cancelled)}")
        
        if prev_cancelled is True:
            logger.info("✅ SUCCESS! Previous order was cancelled!")
        elif prev_cancelled is False:
            logger.warning("❌ Previous order was NOT cancelled")
        else:
            logger.warning("❌ No previous order found (returned None)")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(debug_previous_order_logic())