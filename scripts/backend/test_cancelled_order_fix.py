#!/usr/bin/env python3
"""Test script to verify the previous_order_cancelled field is properly passed to rule engine"""

import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudAnalysis, FraudDetectionRule, User, ShopifyStore
from fraud_rule_processor import FraudRuleProcessor
from rule_engine import RuleEngine
from datetime import datetime, timezone
from decimal import Decimal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_cancelled_order_in_rule_engine():
    """Test that previous_order_cancelled field is properly passed to rule engine"""
    
    db = SessionLocal()
    try:
        # Get a user and store for testing
        user = db.query(User).first()
        store = db.query(ShopifyStore).filter(ShopifyStore.shop_name == "Tobacco Stock").first()
        
        if not user or not store:
            logger.error("No user or Tobacco Stock store found in database")
            return False
        
        logger.info(f"Using user: {user.email}, store: {store.shop_name}")
        
        # Create a mock fraud analysis with previous_order_cancelled = True
        mock_fraud_analysis = FraudAnalysis(
            user_id=user.id,
            store_id=store.id,
            shopify_order_id="test_order_id",
            order_name="TEST-ORDER-001",
            is_first_time_customer=False,
            order_total=Decimal("100.00"),
            customer_name="Test Customer",
            customer_total_orders=5,
            previous_order_cancelled=True,  # This is the key field we're testing
            analysis_timestamp=datetime.now(timezone.utc)
        )
        
        # Initialize the fraud rule processor
        processor = FraudRuleProcessor(db, user, store, None)
        
        # Convert fraud analysis to rule data
        rule_data = processor._convert_fraud_analysis_to_rule_data(mock_fraud_analysis)
        
        # Check if previous_order_cancelled is in the converted data
        if 'previous_order_cancelled' in rule_data:
            logger.info(f"✅ SUCCESS: previous_order_cancelled is in rule data")
            logger.info(f"   Value: {rule_data['previous_order_cancelled']}")
            
            # Test with rule engine
            rule_engine = RuleEngine(db)
            
            # Create a test rule that checks for previous_order_cancelled
            test_rule = {
                "name": "Test Previous Order Cancelled",
                "conditions": {
                    "all": [
                        {
                            "field": "previous_order_cancelled",
                            "operator": "equals",
                            "value": True
                        }
                    ]
                },
                "action": {
                    "type": "add_tag",
                    "params": {"tag": "PREVIOUS_ORDER_CANCELLED"}
                }
            }
            
            # Evaluate the rule conditions directly
            logger.info("\nTesting rule evaluation...")
            # Test individual condition evaluation
            condition = test_rule['conditions']['all'][0]
            matches = rule_engine._evaluate_condition(condition, rule_data)
            
            if matches:
                logger.info("✅ Rule evaluation SUCCESS: The condition matched!")
                logger.info("   The rule engine can properly evaluate previous_order_cancelled")
                return True
            else:
                logger.error("❌ Rule evaluation FAILED: The condition did not match")
                logger.error("   The rule engine cannot evaluate previous_order_cancelled properly")
                return False
        else:
            logger.error("❌ FAILED: previous_order_cancelled is NOT in rule data")
            logger.error("   The field is not being passed to the rule engine")
            return False
            
    except Exception as e:
        logger.error(f"Error during test: {str(e)}", exc_info=True)
        return False
    finally:
        db.close()

def check_existing_fraud_analyses():
    """Check if any existing fraud analyses have previous_order_cancelled data"""
    
    db = SessionLocal()
    try:
        # Query for fraud analyses with previous_order_cancelled = True
        cancelled_analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.previous_order_cancelled == True
        ).limit(5).all()
        
        if cancelled_analyses:
            logger.info(f"\n📊 Found {len(cancelled_analyses)} fraud analyses with previous_order_cancelled = True:")
            for analysis in cancelled_analyses:
                logger.info(f"   - Order: {analysis.order_name}, Store ID: {analysis.store_id}")
        else:
            logger.info("\n📊 No fraud analyses found with previous_order_cancelled = True")
        
        # Query for any fraud analyses with non-null previous_order_cancelled
        any_analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.previous_order_cancelled.isnot(None)
        ).limit(5).all()
        
        if any_analyses:
            logger.info(f"\n📊 Found {len(any_analyses)} fraud analyses with previous_order_cancelled data:")
            for analysis in any_analyses:
                logger.info(f"   - Order: {analysis.order_name}, Cancelled: {analysis.previous_order_cancelled}")
        else:
            logger.info("\n📊 No fraud analyses found with any previous_order_cancelled data")
            
    except Exception as e:
        logger.error(f"Error checking existing analyses: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("="*60)
    logger.info("Testing previous_order_cancelled field in rule engine")
    logger.info("="*60)
    
    # Check existing data
    check_existing_fraud_analyses()
    
    # Run the test
    logger.info("\n" + "="*60)
    logger.info("Testing field conversion and rule evaluation")
    logger.info("="*60)
    
    success = test_cancelled_order_in_rule_engine()
    
    if success:
        logger.info("\n🎉 All tests passed! The fix is working correctly.")
        logger.info("   The previous_order_cancelled field is now properly passed to the rule engine.")
    else:
        logger.error("\n❌ Tests failed. Please check the implementation.")
    
    sys.exit(0 if success else 1)