"""Check if we're getting the full order history including cancelled orders"""

import asyncio
import logging
import json
from database import SessionLocal
from models import ShopifyStore
from enhanced_shopify_client import EnhancedShopifyClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_full_history():
    """Check John Kelley's full order history"""
    
    db = SessionLocal()
    try:
        store = db.query(ShopifyStore).filter(ShopifyStore.is_active == True).first()
        if not store:
            logger.error("No active store found")
            return
        
        client = EnhancedShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        # Get John Kelley's order
        order_data = await client.get_order_with_comprehensive_delivery_data("PW110573")
        
        if not order_data:
            logger.error("Failed to get order data")
            return
        
        # Check full customer order history
        customer = order_data.get('customer', {})
        orders_history = customer.get('orders', {}).get('edges', [])
        
        logger.info(f"Customer has {len(orders_history)} orders in the current query")
        logger.info(f"Customer total orders: {customer.get('numberOfOrders', 0)}")
        
        # Check all orders for cancellations
        logger.info("\nSearching for cancelled orders in history:")
        cancelled_found = False
        
        for i, order_edge in enumerate(orders_history):
            order = order_edge['node']
            cancelled_at = order.get('cancelledAt')
            if cancelled_at:
                logger.info(f"✅ FOUND CANCELLED ORDER!")
                logger.info(f"   Position: {i+1}")
                logger.info(f"   Order: {order['name']}")
                logger.info(f"   Cancelled At: {cancelled_at}")
                cancelled_found = True
        
        if not cancelled_found:
            logger.warning("❌ No cancelled orders found in the returned history")
            logger.info(f"The query only returns {len(orders_history)} orders, but customer has {customer.get('numberOfOrders', 0)} total")
            logger.info("The cancelled order PW19925 might be outside the query limit")
        
        # Save data for inspection
        with open('john_kelley_order_history.json', 'w') as f:
            json.dump(customer, f, indent=2)
        logger.info("\nFull customer data saved to john_kelley_order_history.json")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(check_full_history())