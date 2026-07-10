#!/usr/bin/env python3
"""
Test script to verify fraud duplicate detection values are properly passed to rule evaluation.
This will help diagnose why fraud rules aren't seeing updated duplicate detection values.
"""
import asyncio
import logging
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import User, ShopifyStore, FraudAnalysis, FraudDetectionRule, Settings
from fraud_service import FraudAnalysisService
from fraud_rule_processor import FraudRuleProcessor
from enhanced_shopify_client import EnhancedShopifyClient
import json

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_duplicate_detection_flow(user_id: int, order_name: str):
    """Test the complete flow of duplicate detection from analysis to rule evaluation."""
    
    db = SessionLocal()
    try:
        # Get user and their store
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return
            
        store = db.query(ShopifyStore).filter(
            ShopifyStore.user_id == user_id,
            ShopifyStore.is_active == True
        ).first()
        
        if not store:
            logger.error(f"No active store found for user {user_id}")
            return
            
        logger.info(f"Testing duplicate detection for order {order_name} on store {store.shop_domain}")
        
        # Step 1: Get order data
        logger.info("\n=== STEP 1: FETCHING ORDER DATA ===")
        client = EnhancedShopifyClient(store.shop_domain, store.access_token)
        order_data = await client.get_order_by_name(order_name, include_fraud_data=True)
        
        if not order_data:
            logger.error(f"Order {order_name} not found")
            return
            
        logger.info(f"Order data retrieved successfully")
        
        # Step 2: Run fraud analysis
        logger.info("\n=== STEP 2: RUNNING FRAUD ANALYSIS ===")
        fraud_service = FraudAnalysisService(db, store, user)
        fraud_analysis = fraud_service.analyze_order_fraud(order_data)
        
        if not fraud_analysis:
            logger.error("Fraud analysis failed")
            return
            
        logger.info(f"Fraud analysis created: ID={fraud_analysis.id}")
        logger.info(f"  - duplicate_within_7days: {fraud_analysis.duplicate_within_7days}")
        logger.info(f"  - customer_name: {fraud_analysis.customer_name}")
        logger.info(f"  - is_first_time_customer: {fraud_analysis.is_first_time_customer}")
        
        # Step 3: Get user settings for duplicate detection days
        logger.info("\n=== STEP 3: CHECKING USER SETTINGS ===")
        settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        if settings:
            logger.info(f"User duplicate_detection_days: {settings.duplicate_detection_days}")
        else:
            logger.info("No user settings found, using default 7 days")
        
        # Step 4: Check if we have fraud rules that check duplicate detection
        logger.info("\n=== STEP 4: CHECKING FRAUD RULES ===")
        fraud_rules = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.user_id == user_id,
            FraudDetectionRule.is_active == True
        ).all()
        
        duplicate_rules = []
        for rule in fraud_rules:
            conditions_str = json.dumps(rule.conditions) if rule.conditions else ""
            if 'duplicate_within_7days' in conditions_str:
                duplicate_rules.append(rule)
                logger.info(f"Found rule checking duplicate detection: {rule.name} (ID: {rule.id})")
                logger.info(f"  Conditions: {rule.conditions}")
        
        if not duplicate_rules:
            logger.warning("No active fraud rules found that check duplicate_within_7days")
        
        # Step 5: Test rule processor conversion
        logger.info("\n=== STEP 5: TESTING RULE PROCESSOR CONVERSION ===")
        processor = FraudRuleProcessor(db, user, store)
        
        # Test the conversion method directly
        fraud_data = processor._convert_fraud_analysis_to_rule_data(fraud_analysis)
        logger.info(f"Converted fraud data:")
        logger.info(f"  - duplicate_within_7days: {fraud_data.get('duplicate_within_7days')} (type: {type(fraud_data.get('duplicate_within_7days'))})")
        logger.info(f"  - customer_name: {fraud_data.get('customer_name')}")
        logger.info(f"  - first_time_customer: {fraud_data.get('first_time_customer')}")
        
        # Step 6: Process fraud rules
        logger.info("\n=== STEP 6: PROCESSING FRAUD RULES ===")
        fraud_results = await processor.process_fraud_rules_for_order(order_data, fraud_analysis)
        
        logger.info(f"Fraud rule results:")
        logger.info(f"  - Rules processed: {fraud_results.get('rules_processed', 0)}")
        logger.info(f"  - Rules matched: {fraud_results.get('rules_matched', 0)}")
        
        for result in fraud_results.get('results', []):
            if result.get('rule_name') in [r.name for r in duplicate_rules]:
                logger.info(f"\nRule '{result.get('rule_name')}' evaluation:")
                logger.info(f"  - Matched: {result.get('matched')}")
                logger.info(f"  - Actions executed: {result.get('actions_executed', 0)}")
                if result.get('error'):
                    logger.error(f"  - Error: {result.get('error')}")
        
        # Step 7: Test updating duplicate detection
        logger.info("\n=== STEP 7: TESTING DUPLICATE DETECTION UPDATE ===")
        
        # Simulate changing the duplicate detection value
        old_value = fraud_analysis.duplicate_within_7days
        new_value = not old_value  # Toggle the value
        
        logger.info(f"Updating duplicate_within_7days: {old_value} -> {new_value}")
        fraud_analysis.duplicate_within_7days = new_value
        db.commit()
        db.refresh(fraud_analysis)
        
        logger.info(f"After update: duplicate_within_7days = {fraud_analysis.duplicate_within_7days}")
        
        # Re-process rules with updated value
        logger.info("\n=== STEP 8: RE-PROCESSING WITH UPDATED VALUE ===")
        fraud_results2 = await processor.process_fraud_rules_for_order(order_data, fraud_analysis)
        
        logger.info(f"Re-processed fraud rule results:")
        logger.info(f"  - Rules processed: {fraud_results2.get('rules_processed', 0)}")
        logger.info(f"  - Rules matched: {fraud_results2.get('rules_matched', 0)}")
        
        # Compare results
        if fraud_results.get('rules_matched') != fraud_results2.get('rules_matched'):
            logger.info("✅ Rule matching changed after updating duplicate detection!")
        else:
            logger.warning("⚠️  Rule matching did NOT change after updating duplicate detection")
            
    except Exception as e:
        logger.error(f"Error in test: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 3:
        print("Usage: python test_fraud_duplicate_detection.py <user_id> <order_name>")
        print("Example: python test_fraud_duplicate_detection.py 1 'PW110472'")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    order_name = sys.argv[2]
    
    # Run the async test
    asyncio.run(test_duplicate_detection_flow(user_id, order_name))