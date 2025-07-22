"""Simple test to check if cancelledAt field is being returned"""

import asyncio
import logging
import json
from database import SessionLocal
from models import ShopifyStore
from enhanced_shopify_client import EnhancedShopifyClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_cancelled_field():
    """Test if cancelledAt field is being returned in customer order history"""
    
    db = SessionLocal()
    try:
        # Get an active store
        store = db.query(ShopifyStore).filter(ShopifyStore.is_active == True).first()
        if not store:
            logger.error("No active store found")
            return
        
        logger.info(f"Testing with store: {store.shop_name}")
        
        client = EnhancedShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        # Get a recent order from a repeat customer
        query = """
        query getRecentOrders($first: Int) {
            orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        customer {
                            numberOfOrders
                        }
                    }
                }
            }
        }
        """
        
        result = await client._make_graphql_request(query, {"first": 50})
        orders = result.get("data", {}).get("orders", {}).get("edges", [])
        
        # Find order from repeat customer
        target_order = None
        for order_edge in orders:
            order = order_edge["node"]
            num_orders = order.get("customer", {}).get("numberOfOrders", 0)
            if isinstance(num_orders, str):
                num_orders = int(num_orders) if num_orders.isdigit() else 0
            if num_orders > 5:  # Get customer with more orders
                target_order = order
                break
        
        if not target_order:
            logger.error("No repeat customer orders found")
            return
        
        logger.info(f"Testing with order: {target_order['name']}")
        
        # Now get the full order data
        order_data = await client.get_order_with_comprehensive_delivery_data(target_order['name'])
        
        if not order_data:
            logger.error("Failed to get order data")
            return
        
        # Check customer order history
        customer = order_data.get('customer', {})
        orders_history = customer.get('orders', {}).get('edges', [])
        
        logger.info(f"\nCustomer has {len(orders_history)} orders in history")
        logger.info("Checking first 5 orders for cancelledAt field:")
        
        found_cancelled = False
        for i, order_edge in enumerate(orders_history[:5]):
            order = order_edge['node']
            order_name = order.get('name', 'Unknown')
            cancelled_at = order.get('cancelledAt')
            fields = list(order.keys())
            
            logger.info(f"\nOrder {i+1}: {order_name}")
            logger.info(f"  Fields present: {fields}")
            logger.info(f"  cancelledAt value: {cancelled_at}")
            
            if cancelled_at:
                found_cancelled = True
                logger.info(f"  ✅ FOUND CANCELLED ORDER!")
        
        # Save the full data for inspection
        with open('test_cancelled_order_data.json', 'w') as f:
            json.dump(order_data, f, indent=2)
        logger.info("\nFull order data saved to test_cancelled_order_data.json")
        
        if not found_cancelled:
            logger.warning("\n⚠️  No cancelled orders found in this customer's history")
            logger.info("This might be normal if the customer has no cancelled orders")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_cancelled_field())