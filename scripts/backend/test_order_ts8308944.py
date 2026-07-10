#!/usr/bin/env python3
"""Test script to analyze order TS8308944 and verify the previous_order_cancelled field"""

import logging
import sys
import os
import asyncio
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import User, ShopifyStore, FraudAnalysis, FraudDetectionRule
from fraud_service import FraudAnalysisService
from fraud_rule_processor import FraudRuleProcessor
from shopify_client import ShopifyClient
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_order_ts8308944():
    """Test fraud analysis for order TS8308944"""
    
    db = SessionLocal()
    try:
        # Get user and store
        user = db.query(User).first()
        store = db.query(ShopifyStore).filter(ShopifyStore.shop_name == "Tobacco Stock").first()
        
        if not user or not store:
            logger.error("No user or Tobacco Stock store found")
            return False
        
        logger.info(f"Using user: {user.email}, store: {store.shop_name}")
        
        # Check if order already analyzed
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
            
            # Test rule processing
            processor = FraudRuleProcessor(db, user, store, None)
            rule_data = processor._convert_fraud_analysis_to_rule_data(existing)
            
            logger.info(f"\n🔄 Converted to rule data:")
            logger.info(f"   - previous_order_cancelled in data: {'previous_order_cancelled' in rule_data}")
            logger.info(f"   - Value: {rule_data.get('previous_order_cancelled')}")
            
            # Check if there's a rule for cancelled orders
            cancelled_rules = db.query(FraudDetectionRule).filter(
                FraudDetectionRule.store_id == store.id,
                FraudDetectionRule.is_active == True
            ).all()
            
            for rule in cancelled_rules:
                if rule.conditions and 'previous_order_cancelled' in str(rule.conditions):
                    logger.info(f"\n📋 Found rule checking previous_order_cancelled: {rule.name}")
                    logger.info(f"   Conditions: {rule.conditions}")
            
            return True
        else:
            logger.info("\n⚠️ Order TS8308944 not yet analyzed")
            logger.info("   To analyze this order, you need to:")
            logger.info("   1. Make sure the order exists in Shopify")
            logger.info("   2. Run fraud detection for this specific order")
            
            # Initialize Shopify client
            client = ShopifyClient(store.shop_domain, store.access_token)
            
            # Try to fetch the order
            logger.info("\n🔍 Attempting to fetch order from Shopify...")
            order_data = await client.get_order_for_fraud_analysis("TS8308944")
            
            if order_data:
                logger.info("✅ Order found in Shopify!")
                
                # Analyze the order
                fraud_service = FraudAnalysisService(db, store, user, client)
                fraud_analysis = fraud_service.analyze_order_fraud(order_data)
                
                if fraud_analysis:
                    logger.info(f"\n✅ Fraud analysis completed:")
                    logger.info(f"   - Analysis ID: {fraud_analysis.id}")
                    logger.info(f"   - Is first time customer: {fraud_analysis.is_first_time_customer}")
                    logger.info(f"   - Customer total orders: {fraud_analysis.customer_total_orders}")
                    logger.info(f"   - Previous order cancelled: {fraud_analysis.previous_order_cancelled}")
                    logger.info(f"   - Previous order delivery status: {fraud_analysis.previous_order_delivery_status}")
                    
                    # Now test rule processing
                    processor = FraudRuleProcessor(db, user, store, client)
                    rule_data = processor._convert_fraud_analysis_to_rule_data(fraud_analysis)
                    
                    logger.info(f"\n🔄 Converted to rule data:")
                    logger.info(f"   - previous_order_cancelled in data: {'previous_order_cancelled' in rule_data}")
                    logger.info(f"   - Value: {rule_data.get('previous_order_cancelled')}")
                    
                    # Process fraud rules
                    logger.info("\n🚀 Processing fraud rules...")
                    results = await processor.process_fraud_rules_for_order(fraud_analysis)
                    
                    if results:
                        logger.info(f"✅ Rules processed successfully")
                        for result in results:
                            if result.get('matched'):
                                logger.info(f"   - Rule '{result.get('rule_name')}' matched!")
                                logger.info(f"     Action: {result.get('action')}")
                    
                    return True
                else:
                    logger.error("❌ Failed to analyze order")
                    return False
            else:
                logger.error("❌ Order not found in Shopify")
                logger.info("   Please verify the order number is correct")
                return False
            
    except Exception as e:
        logger.error(f"Error during test: {str(e)}", exc_info=True)
        return False
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("="*60)
    logger.info("Testing Order TS8308944 - Previous Order Cancelled Check")
    logger.info("="*60)
    
    success = asyncio.run(test_order_ts8308944())
    
    if success:
        logger.info("\n✅ Test completed successfully")
    else:
        logger.error("\n❌ Test failed")
    
    sys.exit(0 if success else 1)