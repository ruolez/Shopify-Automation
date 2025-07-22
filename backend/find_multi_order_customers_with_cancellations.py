"""Find customers with multiple orders including cancellations"""

import asyncio
import logging
from database import SessionLocal
from models import ShopifyStore
from shopify_client import ShopifyClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def find_multi_order_customers():
    """Find customers who have both cancelled and non-cancelled orders"""
    
    db = SessionLocal()
    try:
        store = db.query(ShopifyStore).filter(ShopifyStore.is_active == True).first()
        if not store:
            logger.error("No active store found")
            return
        
        logger.info(f"Searching for multi-order customers with cancellations in: {store.shop_name}")
        
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
                            orders(first: 10, sortKey: CREATED_AT, reverse: true) {
                                edges {
                                    node {
                                        id
                                        name
                                        createdAt
                                        cancelledAt
                                        displayFinancialStatus
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        variables = {"first": 250}  # Get more orders to find good candidates
        
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
            
            # Check if customer has multiple orders
            num_orders = customer.get("numberOfOrders", 0)
            if isinstance(num_orders, str):
                num_orders = int(num_orders) if num_orders.isdigit() else 0
            
            if num_orders < 2:
                continue
            
            # Check customer's order history for cancellations
            customer_orders = customer.get('orders', {}).get('edges', [])
            has_cancelled = False
            has_non_cancelled = False
            cancelled_orders = []
            non_cancelled_orders = []
            
            for cust_order_edge in customer_orders:
                cust_order = cust_order_edge['node']
                if cust_order.get('cancelledAt'):
                    has_cancelled = True
                    cancelled_orders.append(cust_order['name'])
                else:
                    has_non_cancelled = True
                    non_cancelled_orders.append(cust_order['name'])
            
            if has_cancelled and has_non_cancelled:
                found_candidates.append({
                    'customer_name': f"{customer.get('firstName', '')} {customer.get('lastName', '')}",
                    'email': customer.get('email', ''),
                    'total_orders': num_orders,
                    'cancelled_orders': cancelled_orders,
                    'active_orders': non_cancelled_orders,
                    'most_recent_order': customer_orders[0]['node']['name'] if customer_orders else None
                })
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Found {len(found_candidates)} customers with both cancelled and active orders:")
        
        for i, candidate in enumerate(found_candidates[:10]):  # Show first 10
            logger.info(f"\n{i+1}. Customer: {candidate['customer_name']}")
            logger.info(f"   Email: {candidate['email']}")
            logger.info(f"   Total Orders: {candidate['total_orders']}")
            logger.info(f"   Cancelled Orders: {', '.join(candidate['cancelled_orders'])}")
            logger.info(f"   Active Orders: {', '.join(candidate['active_orders'][:3])}...")
            logger.info(f"   Most Recent Order: {candidate['most_recent_order']}")
        
        if found_candidates:
            logger.info(f"\n✅ Found {len(found_candidates)} customers to test with!")
            logger.info("These customers have previous cancelled orders that should trigger the rule")
        else:
            logger.warning("\n⚠️  No customers found with both cancelled and active orders")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(find_multi_order_customers())