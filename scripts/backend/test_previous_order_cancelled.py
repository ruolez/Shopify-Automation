"""Test script to verify previous_order_cancelled implementation"""

import logging
from sqlalchemy import create_engine, inspect
from database import get_db, engine
from models import FraudAnalysis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_column_exists():
    """Check if the column exists in the database"""
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('fraud_analyses')]
        
        if 'previous_order_cancelled' in columns:
            logger.info("✅ Column 'previous_order_cancelled' exists in fraud_analyses table")
            return True
        else:
            logger.error("❌ Column 'previous_order_cancelled' NOT found in fraud_analyses table")
            return False
    except Exception as e:
        logger.error(f"Error checking column: {str(e)}")
        return False

def test_field_in_model():
    """Check if the field exists in the SQLAlchemy model"""
    try:
        # Check if the attribute exists in the model
        if hasattr(FraudAnalysis, 'previous_order_cancelled'):
            logger.info("✅ Field 'previous_order_cancelled' exists in FraudAnalysis model")
            return True
        else:
            logger.error("❌ Field 'previous_order_cancelled' NOT found in FraudAnalysis model")
            return False
    except Exception as e:
        logger.error(f"Error checking model: {str(e)}")
        return False

def main():
    """Run all tests"""
    logger.info("Testing previous_order_cancelled implementation...")
    
    tests_passed = 0
    tests_total = 2
    
    # Test 1: Column exists in database
    if test_column_exists():
        tests_passed += 1
    
    # Test 2: Field exists in model
    if test_field_in_model():
        tests_passed += 1
    
    logger.info(f"\nTests passed: {tests_passed}/{tests_total}")
    
    if tests_passed == tests_total:
        logger.info("✅ All tests passed! The previous_order_cancelled field is properly implemented.")
    else:
        logger.error("❌ Some tests failed. Please check the implementation.")

if __name__ == "__main__":
    main()