#!/usr/bin/env python3
"""Test if user context is being passed correctly in fraud service"""

import logging
from database import SessionLocal
from models import User, ShopifyStore, Settings, FraudAnalysis
from fraud_service import FraudAnalysisService

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_user_context_issue(user_id: int, order_name: str):
    """Test if the user context is being passed correctly to fraud service"""
    
    logger.info(f"\n=== TESTING USER CONTEXT ISSUE ===")
    logger.info(f"User ID: {user_id}, Order: {order_name}")
    
    db = SessionLocal()
    try:
        # Get user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return
        
        logger.info(f"User found: {user.email}")
        
        # Get user settings
        settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        if settings:
            logger.info(f"User settings - duplicate_detection_days: {settings.duplicate_detection_days}")
        else:
            logger.warning("No user settings found")
        
        # Get fraud analysis
        analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.order_name == order_name
        ).first()
        
        if not analysis:
            logger.error(f"No fraud analysis found for order {order_name}")
            return
        
        logger.info(f"Fraud analysis found - ID: {analysis.id}")
        
        # Get store
        store = db.query(ShopifyStore).filter(ShopifyStore.id == analysis.store_id).first()
        if not store:
            logger.error(f"Store {analysis.store_id} not found")
            return
        
        logger.info(f"Store found: {store.shop_domain}")
        
        # Test 1: Create fraud service and check user context
        logger.info("\n--- Test 1: Check fraud service user context ---")
        fraud_service = FraudAnalysisService(db, store, user)
        
        logger.info(f"fraud_service.user.id = {fraud_service.user.id}")
        logger.info(f"fraud_service.user.email = {fraud_service.user.email}")
        logger.info(f"fraud_service.store.id = {fraud_service.store.id}")
        logger.info(f"fraud_service.store.shop_domain = {fraud_service.store.shop_domain}")
        
        # Test 2: Check if fraud service can access user settings
        logger.info("\n--- Test 2: Check settings access from fraud service ---")
        
        # Direct query from fraud service's db session
        settings_from_service = fraud_service.db.query(Settings).filter(
            Settings.user_id == fraud_service.user.id
        ).first()
        
        if settings_from_service:
            logger.info(f"Settings accessible from fraud service:")
            logger.info(f"  duplicate_detection_days: {settings_from_service.duplicate_detection_days}")
        else:
            logger.warning("No settings found from fraud service context")
        
        # Test 3: Check if the db sessions are the same
        logger.info("\n--- Test 3: Check database sessions ---")
        logger.info(f"Main db session: {id(db)}")
        logger.info(f"Fraud service db session: {id(fraud_service.db)}")
        logger.info(f"Sessions are same? {db is fraud_service.db}")
        
        # Test 4: Try creating a test fraud analysis with the service
        logger.info("\n--- Test 4: Test fraud analysis creation ---")
        
        # Create a mock order data
        mock_order_data = {
            "id": "gid://shopify/Order/TEST123",
            "name": "TEST-ORDER",
            "createdAt": "2024-01-01T00:00:00Z",
            "customer": {
                "id": "gid://shopify/Customer/TEST",
                "numberOfOrders": 5,
                "orders": {
                    "edges": []
                }
            }
        }
        
        # Check what the fraud service would calculate
        duplicate_result = fraud_service._check_duplicate_within_configurable_days(mock_order_data)
        logger.info(f"Test duplicate detection result: {duplicate_result}")
        
        # Test 5: Check if there's a transaction issue
        logger.info("\n--- Test 5: Transaction isolation test ---")
        
        # Start a new transaction
        db.begin()
        
        # Try to update a value
        if settings:
            old_value = settings.duplicate_detection_days
            settings.duplicate_detection_days = 999
            db.flush()  # Flush but don't commit
            
            # Check if fraud service sees the change
            settings_check = fraud_service.db.query(Settings).filter(
                Settings.user_id == user_id
            ).first()
            
            if settings_check:
                logger.info(f"Fraud service sees duplicate_detection_days as: {settings_check.duplicate_detection_days}")
                logger.info(f"Expected to see: 999 (if same transaction), or {old_value} (if different)")
            
            # Rollback
            db.rollback()
            logger.info("Rolled back test transaction")
        
    except Exception as e:
        logger.error(f"Test failed: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 3:
        print("Usage: python test_user_context_issue.py <user_id> <order_name>")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    order_name = sys.argv[2]
    
    test_user_context_issue(user_id, order_name)