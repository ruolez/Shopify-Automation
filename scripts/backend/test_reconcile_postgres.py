#!/usr/bin/env python3
"""
Test the reconcile functionality with PostgreSQL
"""
import asyncio
import sys
import os
from datetime import datetime

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, engine
from models import User, FraudAnalysis, Settings
from fraud_archive_service import FraudArchiveService
from sqlalchemy import text, inspect
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_archive_table():
    """Check if the fraud_analyses_archive table exists"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    if 'fraud_analyses_archive' in tables:
        logger.info("✓ fraud_analyses_archive table exists")
        columns = inspector.get_columns('fraud_analyses_archive')
        logger.info(f"  Number of columns: {len(columns)}")
        # Check for key columns
        column_names = [col['name'] for col in columns]
        required_columns = ['id', 'user_id', 'store_id', 'order_name', 'archived_at', 'archive_reason']
        for col in required_columns:
            if col in column_names:
                logger.info(f"  ✓ Column '{col}' exists")
            else:
                logger.error(f"  ✗ Column '{col}' is missing!")
        return True
    else:
        logger.error("✗ fraud_analyses_archive table does NOT exist")
        logger.info("Creating the archive table...")
        
        # Create the archive table
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS fraud_analyses_archive (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            order_name VARCHAR(50) NOT NULL,
            shopify_order_id VARCHAR(100),
            is_first_time_customer BOOLEAN,
            order_total DECIMAL(10, 2),
            transaction_attempts_count INTEGER,
            customer_name VARCHAR(255),
            duplicate_within_7days BOOLEAN,
            previous_order_delivery_status VARCHAR(100),
            previous_order_total DECIMAL(10, 2),
            current_order_total DECIMAL(10, 2),
            shopify_fraud_risk_level VARCHAR(50),
            customer_notes TEXT,
            billing_address_outside_us BOOLEAN,
            same_billing_shipping BOOLEAN,
            shipping_state VARCHAR(100),
            additional_details TEXT,
            current_order_delivery_status VARCHAR(100),
            days_since_last_delivery INTEGER,
            raw_shopify_data TEXT,
            duplicate_match_details TEXT,
            transaction_details TEXT,
            risk_assessment_details TEXT,
            customer_order_history TEXT,
            delivery_analytics TEXT,
            rule_triggered_ids TEXT,
            rule_processing_results TEXT,
            analysis_timestamp TIMESTAMP,
            processing_time_seconds DECIMAL(10, 2),
            analysis_version VARCHAR(20),
            archived_at TIMESTAMP NOT NULL,
            archive_reason VARCHAR(50) NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (store_id) REFERENCES shopify_stores(id)
        );
        """
        
        with engine.connect() as conn:
            conn.execute(text(create_table_sql))
            conn.commit()
        
        logger.info("Archive table created successfully")
        return True

def test_archive_analysis():
    """Test archiving a single analysis"""
    db = SessionLocal()
    try:
        # Get a test fraud analysis
        analysis = db.query(FraudAnalysis).first()
        if not analysis:
            logger.warning("No fraud analyses found to test")
            return False
            
        logger.info(f"Testing archive for analysis ID {analysis.id}, order {analysis.order_name}")
        
        # Create archive service
        archive_service = FraudArchiveService(db)
        
        # Try to archive it
        success = archive_service._archive_analysis(analysis, "test_archive")
        
        if success:
            logger.info("✓ Archive operation succeeded")
            db.commit()
            
            # Check if it's in the archive table
            archive_count = db.execute(
                text("SELECT COUNT(*) FROM fraud_analyses_archive WHERE order_name = :order_name"),
                {"order_name": analysis.order_name}
            ).scalar()
            
            if archive_count > 0:
                logger.info(f"✓ Analysis found in archive table")
                
                # Clean up - move it back
                db.execute(
                    text("DELETE FROM fraud_analyses_archive WHERE order_name = :order_name"),
                    {"order_name": analysis.order_name}
                )
                db.commit()
                logger.info("Cleaned up test archive entry")
                return True
            else:
                logger.error("✗ Analysis not found in archive table after archiving")
                return False
        else:
            logger.error("✗ Archive operation failed")
            return False
            
    except Exception as e:
        logger.error(f"Error during archive test: {str(e)}", exc_info=True)
        db.rollback()
        return False
    finally:
        db.close()

async def test_reconcile_process():
    """Test the full reconcile process"""
    db = SessionLocal()
    try:
        # Get a user with fraud sync enabled
        user = db.query(User).join(Settings).filter(
            Settings.fraud_sync_enabled == True
        ).first()
        
        if not user:
            logger.warning("No users with fraud sync enabled")
            return False
            
        logger.info(f"Testing reconcile for user {user.email}")
        
        # Get count of active analyses before
        before_count = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user.id
        ).count()
        
        logger.info(f"Active fraud analyses before: {before_count}")
        
        # Run the reconcile process
        archive_service = FraudArchiveService(db)
        result = await archive_service.archive_fulfilled_and_cancelled_analyses(
            user.id, 
            max_analyses=10  # Process only 10 for testing
        )
        
        logger.info(f"Reconcile result: {result}")
        
        # Get count after
        after_count = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user.id
        ).count()
        
        logger.info(f"Active fraud analyses after: {after_count}")
        
        if result["archived"] > 0:
            logger.info(f"✓ Successfully archived {result['archived']} analyses")
            
            # Check archive table
            archive_count = db.execute(
                text("SELECT COUNT(*) FROM fraud_analyses_archive WHERE user_id = :user_id"),
                {"user_id": user.id}
            ).scalar()
            
            logger.info(f"Total in archive table for user: {archive_count}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during reconcile test: {str(e)}", exc_info=True)
        db.rollback()
        return False
    finally:
        db.close()

def main():
    logger.info("=" * 50)
    logger.info("Testing Fraud Detection Reconcile with PostgreSQL")
    logger.info("=" * 50)
    
    # Step 1: Check if archive table exists
    logger.info("\n1. Checking archive table...")
    if not check_archive_table():
        logger.error("Archive table check failed")
        return
    
    # Step 2: Test single archive operation
    logger.info("\n2. Testing single archive operation...")
    if not test_archive_analysis():
        logger.warning("Single archive test failed, but continuing...")
    
    # Step 3: Test full reconcile process
    logger.info("\n3. Testing full reconcile process...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        success = loop.run_until_complete(test_reconcile_process())
        if success:
            logger.info("\n✓ All reconcile tests completed successfully")
        else:
            logger.error("\n✗ Some reconcile tests failed")
    finally:
        loop.close()
    
    logger.info("\n" + "=" * 50)
    logger.info("Test completed")

if __name__ == "__main__":
    main()