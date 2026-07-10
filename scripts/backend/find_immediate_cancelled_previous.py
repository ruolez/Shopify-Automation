"""Find customers whose immediate previous order was cancelled"""

import asyncio
import logging
from database import SessionLocal
from models import ShopifyStore
from shopify_client import ShopifyClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def find_immediate_cancelled_previous():
    """Find customers whose immediate previous order was cancelled"""
    
    db = SessionLocal()
    try:
        store = db.query(ShopifyStore).filter(ShopifyStore.is_active == True).first()
        if not store:
            logger.error("No active store found")
            return
        
        logger.info(f"Searching for customers with immediately cancelled previous orders in: {store.shop_name}")
        
        client = ShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        # Get recent orders
        query = """
        query getRecentOrders($first: Int) {
            orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        createdAt
                        cancelledAt
                        customer {
                            id
                            firstName
                            lastName
                            email
                            numberOfOrders
                            orders(first: 5, sortKey: CREATED_AT, reverse: true) {
                                edges {
                                    node {
                                        id
                                        name
                                        createdAt
                                        cancelledAt
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        variables = {"first": 250}
        
        result = await client._make_graphql_request(query, variables)
        orders = result.get("data", {}).get("orders", {}).get("edges", [])
        
        logger.info(f"Checking {len(orders)} recent orders...")
        
        # Track customers we've already checked
        checked_customers = set()
        found_candidates = []
        
        for order_edge in orders:
            order = order_edge["node"]
            customer = order.get("customer", {})
            
            if not customer:
                continue
            
            customer_id = customer.get("id")
            if customer_id in checked_customers:
                continue
            
            checked_customers.add(customer_id)
            
            # Get customer's order history
            customer_orders = customer.get('orders', {}).get('edges', [])
            
            # Need at least 2 orders to have a previous order
            if len(customer_orders) < 2:
                continue
            
            # Check if the second most recent order (immediate previous) was cancelled
            # Index 0 is current order, index 1 is immediate previous
            if len(customer_orders) >= 2:
                immediate_previous = customer_orders[1]['node']
                if immediate_previous.get('cancelledAt'):
                    found_candidates.append({
                        'customer_name': f"{customer.get('firstName', '')} {customer.get('lastName', '')}",
                        'email': customer.get('email', ''),
                        'current_order': customer_orders[0]['node']['name'],
                        'previous_order': immediate_previous['name'],
                        'previous_cancelled_at': immediate_previous['cancelledAt'],
                        'total_orders': customer.get('numberOfOrders', 0)
                    })
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Found {len(found_candidates)} customers with immediately cancelled previous orders:")
        
        for i, candidate in enumerate(found_candidates[:10]):  # Show first 10
            logger.info(f"\n{i+1}. Customer: {candidate['customer_name']}")
            logger.info(f"   Email: {candidate['email']}")
            logger.info(f"   Current Order: {candidate['current_order']} (should trigger the rule)")
            logger.info(f"   Previous Order: {candidate['previous_order']} (CANCELLED at {candidate['previous_cancelled_at']})")
            logger.info(f"   Total Orders: {candidate['total_orders']}")
        
        if found_candidates:
            logger.info(f"\n✅ Found {len(found_candidates)} customers with immediately cancelled previous orders!")
            logger.info("These orders SHOULD trigger the previous_order_cancelled rule")
        else:
            logger.warning("\n⚠️  No customers found with immediately cancelled previous orders")
            logger.info("This explains why all 1800 orders showed negative - it's rare for the immediate previous order to be cancelled")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(find_immediate_cancelled_previous())