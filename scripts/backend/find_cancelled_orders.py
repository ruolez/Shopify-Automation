"""Find orders with cancellations to test the implementation"""

import asyncio
import logging
from database import SessionLocal
from models import ShopifyStore
from shopify_client import ShopifyClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def find_cancelled_orders():
    """Search for cancelled orders in the Shopify store"""
    
    db = SessionLocal()
    try:
        # Get an active store
        store = db.query(ShopifyStore).filter(ShopifyStore.is_active == True).first()
        if not store:
            logger.error("No active store found")
            return
        
        logger.info(f"Searching for cancelled orders in store: {store.shop_name}")
        
        client = ShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        # Search for cancelled orders using Shopify's financial status filter
        query = """
        query getCancelledOrders($first: Int, $query: String) {
            orders(first: $first, query: $query, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        createdAt
                        cancelledAt
                        cancelReason
                        displayFinancialStatus
                        displayFulfillmentStatus
                        customer {
                            id
                            firstName
                            lastName
                            numberOfOrders
                        }
                        totalPriceSet {
                            shopMoney {
                                amount
                            }
                        }
                    }
                }
                pageInfo {
                    hasNextPage
                }
            }
        }
        """
        
        # Search for cancelled orders
        variables = {
            "first": 50,
            "query": "financial_status:cancelled OR fulfillment_status:cancelled"
        }
        
        result = await client._make_graphql_request(query, variables)
        orders = result.get("data", {}).get("orders", {}).get("edges", [])
        
        logger.info(f"\nFound {len(orders)} cancelled orders")
        
        cancelled_count = 0
        for order_edge in orders:
            order = order_edge["node"]
            if order.get("cancelledAt"):
                cancelled_count += 1
                customer = order.get("customer", {})
                logger.info(f"\nCancelled Order: {order['name']}")
                logger.info(f"  Cancelled At: {order['cancelledAt']}")
                logger.info(f"  Cancel Reason: {order.get('cancelReason', 'N/A')}")
                logger.info(f"  Customer: {customer.get('firstName', '')} {customer.get('lastName', '')}")
                logger.info(f"  Customer Total Orders: {customer.get('numberOfOrders', 0)}")
                logger.info(f"  Financial Status: {order.get('displayFinancialStatus')}")
        
        if cancelled_count == 0:
            logger.warning("\n⚠️  No orders with cancelledAt timestamp found")
            logger.info("This store might not have any cancelled orders")
        else:
            logger.info(f"\n✅ Found {cancelled_count} orders with cancellation timestamps")
            logger.info("The previous_order_cancelled feature should work for customers who have these orders")
        
        # Also search using a different approach - look for refunded orders
        logger.info("\n" + "="*60)
        logger.info("Also searching for refunded orders...")
        
        variables = {
            "first": 50,
            "query": "financial_status:refunded OR financial_status:partially_refunded"
        }
        
        result = await client._make_graphql_request(query, variables)
        refunded_orders = result.get("data", {}).get("orders", {}).get("edges", [])
        
        logger.info(f"Found {len(refunded_orders)} refunded orders")
        
        for order_edge in refunded_orders[:5]:  # Show first 5
            order = order_edge["node"]
            logger.info(f"\nRefunded Order: {order['name']}")
            logger.info(f"  Cancelled At: {order.get('cancelledAt', 'None')}")
            logger.info(f"  Financial Status: {order.get('displayFinancialStatus')}")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(find_cancelled_orders())