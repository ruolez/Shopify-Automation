"""Test fraud analysis with a known cancelled order"""

import asyncio
import logging
from database import SessionLocal
from models import ShopifyStore, User, FraudAnalysis
from fraud_service import FraudAnalysisService
from enhanced_shopify_client import EnhancedShopifyClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_cancelled_order_analysis():
    """Test if a customer with a cancelled order gets flagged properly"""
    
    db = SessionLocal()
    try:
        # Get an active store
        store = db.query(ShopifyStore).filter(ShopifyStore.is_active == True).first()
        if not store:
            logger.error("No active store found")
            return
        
        user = db.query(User).filter(User.id == store.user_id).first()
        if not user:
            logger.error("No user found for store")
            return
        
        logger.info(f"Testing with store: {store.shop_name}")
        
        # Find customers who have the cancelled orders we found
        cancelled_orders = ["PW110604", "PW110574", "PW110544"]
        
        client = EnhancedShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        # Get customer info for these cancelled orders
        for cancelled_order_name in cancelled_orders:
            logger.info(f"\n{'='*60}")
            logger.info(f"Checking cancelled order: {cancelled_order_name}")
            
            # Get the cancelled order's customer
            query = """
            query getOrder($orderName: String!) {
                orders(first: 1, query: $orderName) {
                    edges {
                        node {
                            id
                            name
                            cancelledAt
                            customer {
                                id
                                firstName
                                lastName
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
            
            variables = {"orderName": f"name:{cancelled_order_name}"}
            result = await client._make_graphql_request(query, variables)
            
            orders = result.get("data", {}).get("orders", {}).get("edges", [])
            if not orders:
                logger.warning(f"Order {cancelled_order_name} not found")
                continue
            
            order = orders[0]["node"]
            customer = order.get("customer", {})
            
            if not customer:
                logger.warning(f"No customer found for order {cancelled_order_name}")
                continue
            
            logger.info(f"Customer: {customer.get('firstName', '')} {customer.get('lastName', '')}")
            logger.info(f"Customer total orders: {customer.get('numberOfOrders', 0)}")
            
            # Show customer's order history
            customer_orders = customer.get('orders', {}).get('edges', [])
            logger.info(f"\nCustomer's recent orders:")
            for i, order_edge in enumerate(customer_orders):
                order_node = order_edge['node']
                logger.info(f"  {i+1}. {order_node['name']} - cancelledAt: {order_node.get('cancelledAt', 'None')}")
            
            # Now find the customer's most recent order (not the cancelled one)
            most_recent_order = None
            for order_edge in customer_orders:
                order_node = order_edge['node']
                if order_node['name'] != cancelled_order_name:
                    most_recent_order = order_node
                    break
            
            if not most_recent_order:
                logger.info("No other orders found for this customer")
                continue
            
            logger.info(f"\nTesting fraud analysis for order: {most_recent_order['name']}")
            
            # Get full order data and run fraud analysis
            order_data = await client.get_order_with_comprehensive_delivery_data(most_recent_order['name'])
            
            if order_data:
                # Create fraud analysis service
                fraud_service = FraudAnalysisService(db, store, user)
                
                # Test the specific method
                prev_cancelled = fraud_service._check_previous_order_cancelled(order_data)
                logger.info(f"✅ _check_previous_order_cancelled result: {prev_cancelled}")
                
                # Run full fraud analysis
                fraud_analysis = fraud_service.analyze_order_fraud(order_data)
                
                if fraud_analysis:
                    logger.info(f"✅ Fraud analysis created with ID: {fraud_analysis.id}")
                    logger.info(f"   previous_order_cancelled: {fraud_analysis.previous_order_cancelled}")
                    
                    # Check if it was saved correctly
                    saved_analysis = db.query(FraudAnalysis).filter(
                        FraudAnalysis.id == fraud_analysis.id
                    ).first()
                    
                    if saved_analysis:
                        logger.info(f"✅ Database check - previous_order_cancelled: {saved_analysis.previous_order_cancelled}")
                    
                    # Clean up test data
                    db.delete(fraud_analysis)
                    db.commit()
                    logger.info("   (Test analysis deleted)")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_cancelled_order_analysis())