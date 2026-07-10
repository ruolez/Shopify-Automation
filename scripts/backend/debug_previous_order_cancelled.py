"""Debug script to investigate why previous_order_cancelled is not triggering"""

import asyncio
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import FraudAnalysis, User, ShopifyStore
from enhanced_shopify_client import EnhancedShopifyClient
import json

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def check_graphql_query(store):
    """Check if cancelledAt is being fetched in GraphQL query"""
    logger.info("=" * 80)
    logger.info("STEP 1: Checking GraphQL query for cancelledAt field")
    logger.info("=" * 80)
    
    client = EnhancedShopifyClient(
        shop_domain=store.shop_domain,
        access_token=store.access_token
    )
    
    # Get a sample order with customer history
    try:
        # First get some orders
        query = """
        query getOrders($first: Int) {
            orders(first: $first, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        customer {
                            id
                            numberOfOrders
                        }
                    }
                }
            }
        }
        """
        
        result = await client._make_graphql_request(query, {"first": 10})
        orders = result.get("data", {}).get("orders", {}).get("edges", [])
        
        # Find an order from a repeat customer
        target_order = None
        for order_edge in orders:
            order = order_edge["node"]
            num_orders = order.get("customer", {}).get("numberOfOrders", 0)
            if isinstance(num_orders, str):
                num_orders = int(num_orders) if num_orders.isdigit() else 0
            if num_orders > 1:
                target_order = order
                break
        
        if not target_order:
            logger.warning("No repeat customer orders found to test")
            return
        
        logger.info(f"Testing with order: {target_order['name']}")
        
        # Now fetch this order with our comprehensive query
        order_data = await client.get_order_with_comprehensive_delivery_data(target_order['name'])
        
        if order_data:
            # Check if customer order history includes cancelledAt
            customer = order_data.get('customer', {})
            orders_history = customer.get('orders', {}).get('edges', [])
            
            logger.info(f"Customer has {len(orders_history)} orders in history")
            
            # Check each historical order for cancelledAt field
            for i, order_edge in enumerate(orders_history[:3]):
                order = order_edge['node']
                cancelled_at = order.get('cancelledAt')
                logger.info(f"Order {i+1} ({order.get('name')}): cancelledAt = {cancelled_at}")
                
                # Log all fields to see what we're getting
                logger.debug(f"Order {i+1} fields: {list(order.keys())}")
            
            # Save raw data for inspection
            with open('debug_order_data.json', 'w') as f:
                json.dump(order_data, f, indent=2)
            logger.info("Full order data saved to debug_order_data.json")
            
    except Exception as e:
        logger.error(f"Error checking GraphQL query: {str(e)}")

def check_database_values(db: Session):
    """Check actual database values for previous_order_cancelled"""
    logger.info("=" * 80)
    logger.info("STEP 2: Checking database values")
    logger.info("=" * 80)
    
    try:
        # Get fraud analyses with their previous_order_cancelled values
        query = text("""
            SELECT 
                id,
                order_name,
                is_first_time_customer,
                previous_order_cancelled,
                previous_order_delivery_status,
                customer_total_orders,
                analysis_timestamp
            FROM fraud_analyses 
            ORDER BY analysis_timestamp DESC 
            LIMIT 50
        """)
        
        results = db.execute(query).fetchall()
        
        # Count statistics
        total = len(results)
        nulls = sum(1 for r in results if r[3] is None)
        trues = sum(1 for r in results if r[3] is True)
        falses = sum(1 for r in results if r[3] is False)
        
        logger.info(f"Analyzed {total} recent fraud analyses:")
        logger.info(f"  - NULL values: {nulls}")
        logger.info(f"  - TRUE values: {trues}")
        logger.info(f"  - FALSE values: {falses}")
        
        # Show some examples
        logger.info("\nSample records:")
        for i, row in enumerate(results[:10]):
            logger.info(f"  {row[1]}: first_time={row[2]}, prev_cancelled={row[3]}, " + 
                       f"prev_delivery='{row[4]}', total_orders={row[5]}")
        
        # Check for any non-first-time customers
        non_first_time = [r for r in results if not r[2]]
        logger.info(f"\nNon-first-time customers: {len(non_first_time)}")
        
    except Exception as e:
        logger.error(f"Error checking database: {str(e)}")

def check_raw_data(db: Session):
    """Check raw Shopify data stored in fraud analyses"""
    logger.info("=" * 80)
    logger.info("STEP 3: Checking raw Shopify data for cancelledAt")
    logger.info("=" * 80)
    
    try:
        # Get a few fraud analyses with raw data
        analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.is_first_time_customer == False
        ).order_by(FraudAnalysis.analysis_timestamp.desc()).limit(5).all()
        
        for analysis in analyses:
            logger.info(f"\nChecking order {analysis.order_name}:")
            
            if analysis.raw_shopify_data:
                # Check if customer order history exists
                customer = analysis.raw_shopify_data.get('customer', {})
                orders = customer.get('orders', {}).get('edges', [])
                
                if orders and len(orders) > 1:
                    # Check second order (first previous)
                    prev_order = orders[1]['node']
                    cancelled_at = prev_order.get('cancelledAt')
                    
                    logger.info(f"  Previous order: {prev_order.get('name')}")
                    logger.info(f"  cancelledAt field: {cancelled_at}")
                    logger.info(f"  Available fields: {list(prev_order.keys())[:10]}...")
                else:
                    logger.info("  No previous orders in raw data")
            else:
                logger.info("  No raw data stored")
                
    except Exception as e:
        logger.error(f"Error checking raw data: {str(e)}")

async def test_specific_order(store, order_name):
    """Test the logic for a specific order"""
    logger.info("=" * 80)
    logger.info(f"STEP 4: Testing specific order {order_name}")
    logger.info("=" * 80)
    
    db = SessionLocal()
    try:
        from fraud_service import FraudAnalysisService
        user = db.query(User).filter(User.id == store.user_id).first()
        
        service = FraudAnalysisService(db, store, user)
        
        # Get order data
        client = EnhancedShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        order_data = await client.get_order_with_comprehensive_delivery_data(order_name)
        
        if order_data:
            # Test the specific method
            result = service._check_previous_order_cancelled(order_data)
            logger.info(f"_check_previous_order_cancelled result: {result}")
            
            # Also check what _get_previous_order_data returns
            delivery_status, total, prev_data = service._get_previous_order_data(order_data)
            if prev_data:
                logger.info(f"Previous order: {prev_data.get('name')}")
                logger.info(f"Previous order cancelledAt: {prev_data.get('cancelledAt')}")
            else:
                logger.info("No previous order data found")
                
    except Exception as e:
        logger.error(f"Error testing specific order: {str(e)}")
    finally:
        db.close()

async def main():
    """Run all debugging checks"""
    db = SessionLocal()
    
    try:
        # Get a store to test with
        store = db.query(ShopifyStore).filter(ShopifyStore.is_active == True).first()
        if not store:
            logger.error("No active store found")
            return
        
        logger.info(f"Testing with store: {store.shop_name}")
        
        # Run checks
        await check_graphql_query(store)
        check_database_values(db)
        check_raw_data(db)
        
        # Test a specific order if you have one
        # await test_specific_order(store, "#1234")
        
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())