#!/usr/bin/env python3
"""
Manually trigger fraud analysis for order TS8308944 from Tobacco Stock
"""

import sys
import os
import asyncio
from datetime import datetime
import logging

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import ShopifyStore, FraudAnalysis, User, FraudDetectionRule
from enhanced_shopify_client import EnhancedShopifyClient
from fraud_service import FraudAnalysisService
from fraud_rule_processor import FraudRuleProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def analyze_order_ts8308944():
    db = SessionLocal()
    try:
        # Get store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.shop_name == "Tobacco Stock"
        ).first()
        
        user = db.query(User).first()
        
        if not store:
            logger.error("Tobacco Stock store not found!")
            return
            
        logger.info(f"Analyzing order TS8308944 for store {store.shop_name}")
        
        # Check if already analyzed
        existing = db.query(FraudAnalysis).filter(
            FraudAnalysis.store_id == store.id,
            FraudAnalysis.order_name == "TS8308944"
        ).first()
        
        if existing:
            logger.info(f"\n📊 Order TS8308944 already analyzed:")
            logger.info(f"   - Analysis ID: {existing.id}")
            logger.info(f"   - Is first time customer: {existing.is_first_time_customer}")
            logger.info(f"   - Customer total orders: {existing.customer_total_orders}")
            logger.info(f"   - Previous order cancelled: {existing.previous_order_cancelled}")
            logger.info(f"   - Previous order delivery status: {existing.previous_order_delivery_status}")
            
            # Test rule processing with the fix
            processor = FraudRuleProcessor(db, user, store, None)
            rule_data = processor._convert_fraud_analysis_to_rule_data(existing)
            
            logger.info(f"\n🔄 Converted to rule data:")
            logger.info(f"   - previous_order_cancelled in data: {'previous_order_cancelled' in rule_data}")
            logger.info(f"   - Value: {rule_data.get('previous_order_cancelled')}")
            
            # Check active rules
            rules = db.query(FraudDetectionRule).filter(
                FraudDetectionRule.store_id == store.id,
                FraudDetectionRule.is_active == True
            ).all()
            
            logger.info(f"\n📋 Active fraud rules for store: {len(rules)}")
            for rule in rules:
                conditions_str = str(rule.conditions) if rule.conditions else ""
                if 'previous_order_cancelled' in conditions_str or 'last' in rule.name.lower() and 'cancel' in rule.name.lower():
                    logger.info(f"\n🎯 Found relevant rule: {rule.name}")
                    logger.info(f"   Conditions: {rule.conditions}")
                    logger.info(f"   Action: {rule.action}")
                    
                    # Test if this rule would match
                    from rule_engine import RuleEngine
                    engine = RuleEngine(db)
                    
                    # Extract conditions for evaluation
                    if isinstance(rule.conditions, dict):
                        if 'all' in rule.conditions:
                            conditions = rule.conditions['all']
                        elif 'any' in rule.conditions:
                            conditions = rule.conditions['any']
                        else:
                            conditions = []
                            
                        for condition in conditions:
                            if condition.get('field') == 'previous_order_cancelled':
                                result = engine._evaluate_condition(condition, rule_data)
                                logger.info(f"\n   🔍 Evaluating condition:")
                                logger.info(f"      Field: {condition.get('field')}")
                                logger.info(f"      Operator: {condition.get('operator')}")
                                logger.info(f"      Expected: {condition.get('value')}")
                                logger.info(f"      Actual: {rule_data.get('previous_order_cancelled')}")
                                logger.info(f"      Result: {'✅ MATCH' if result else '❌ NO MATCH'}")
            
            return
        
        # Initialize enhanced client
        client = EnhancedShopifyClient(store.shop_domain, store.access_token)
        
        # Get order data
        logger.info("Fetching order data from Shopify...")
        order_data = await client.get_order_with_comprehensive_delivery_data("TS8308944")
        
        if not order_data:
            logger.error("Order TS8308944 not found in Shopify!")
            return
            
        logger.info(f"Order found: {order_data.get('name', 'Unknown')}")
        logger.info(f"Created at: {order_data.get('createdAt', 'Unknown')}")
        
        # Check customer info
        customer = order_data.get('customer', {})
        if customer:
            logger.info(f"Customer: {customer.get('displayName', 'Unknown')}")
            orders = customer.get('orders', {}).get('edges', [])
            logger.info(f"Customer total orders: {len(orders)}")
            
            # Check for cancelled orders in history
            for i, order_edge in enumerate(orders[:5]):  # Check first 5 orders
                order = order_edge['node']
                order_name = order.get('name')
                cancelled_at = order.get('cancelledAt')
                if cancelled_at:
                    logger.info(f"   📍 Order {order_name}: CANCELLED at {cancelled_at}")
                else:
                    logger.info(f"   Order {order_name}: Not cancelled")
        
        # Run fraud analysis
        logger.info("\nRunning fraud analysis...")
        fraud_service = FraudAnalysisService(db, store, user)
        fraud_analysis = fraud_service.analyze_order_fraud(order_data)
        
        if fraud_analysis:
            logger.info(f"\n✅ Fraud analysis completed!")
            logger.info(f"   - Analysis ID: {fraud_analysis.id}")
            logger.info(f"   - Risk level: {fraud_analysis.shopify_fraud_risk_level}")
            logger.info(f"   - First time customer: {fraud_analysis.is_first_time_customer}")
            logger.info(f"   - Customer total orders: {fraud_analysis.customer_total_orders}")
            logger.info(f"   - Previous order cancelled: {fraud_analysis.previous_order_cancelled}")
            logger.info(f"   - Previous order delivery: {fraud_analysis.previous_order_delivery_status}")
            
            # Process fraud rules
            logger.info("\nProcessing fraud detection rules...")
            processor = FraudRuleProcessor(db, user, store, client)
            results = await processor.process_fraud_rules_for_order(fraud_analysis)
            
            if results:
                logger.info(f"✅ Fraud rules processed!")
                logger.info(f"   Results: {results}")
            else:
                logger.info("No matching fraud rules found")
        else:
            logger.error("❌ Fraud analysis failed!")
            
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(analyze_order_ts8308944())