"""
Remove age_checker_detected column from fraud_analyses_archive table.

This migration removes the age_checker_detected column that was removed from
the main fraud_analyses table but still exists in the archive table.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Remove age_checker_detected column from fraud_analyses_archive table"""
    # Get database URL from environment or use default
    database_url = os.getenv("DATABASE_URL", "sqlite:///./shopify_automation.db")
    engine = create_engine(database_url)
    
    try:
        with engine.begin() as conn:
            # First, check if the column exists
            check_column_sql = """
            SELECT COUNT(*) as col_count
            FROM pragma_table_info('fraud_analyses_archive')
            WHERE name = 'age_checker_detected'
            """
            
            result = conn.execute(text(check_column_sql)).fetchone()
            
            if result and result.col_count > 0:
                logger.info("age_checker_detected column found in fraud_analyses_archive table")
                
                # SQLite doesn't support DROP COLUMN directly, so we need to:
                # 1. Create a new table without the column
                # 2. Copy data from old table
                # 3. Drop old table
                # 4. Rename new table
                
                # Create new table without age_checker_detected
                create_new_table_sql = """
                CREATE TABLE fraud_analyses_archive_new (
                    -- Core identification
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    store_id INTEGER NOT NULL,
                    order_name VARCHAR NOT NULL,
                    shopify_order_id VARCHAR NOT NULL,
                    
                    -- ALL fraud detection data points (without age_checker_detected)
                    is_first_time_customer BOOLEAN,
                    order_total NUMERIC(12, 2),
                    transaction_attempts_count INTEGER,
                    customer_name VARCHAR,
                    duplicate_within_7days BOOLEAN,
                    previous_order_delivery_status VARCHAR,
                    previous_order_total NUMERIC(12, 2),
                    current_order_total NUMERIC(12, 2),
                    shopify_fraud_risk_level VARCHAR,
                    customer_notes TEXT,
                    billing_address_outside_us BOOLEAN,
                    same_billing_shipping BOOLEAN,
                    shipping_state VARCHAR,
                    additional_details TEXT,
                    current_order_delivery_status VARCHAR,
                    days_since_last_delivery INTEGER,
                    
                    -- Supporting data
                    raw_shopify_data TEXT,
                    duplicate_match_details TEXT,
                    transaction_details TEXT,
                    risk_assessment_details TEXT,
                    customer_order_history TEXT,
                    delivery_analytics TEXT,
                    
                    -- Fraud rule processing tracking
                    rule_triggered_ids TEXT,
                    rule_processing_results TEXT,
                    
                    -- Analysis metadata
                    analysis_timestamp DATETIME,
                    processing_time_seconds NUMERIC(8, 4),
                    analysis_version VARCHAR DEFAULT '1.0',
                    
                    -- Archive-specific columns
                    archived_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    archive_reason VARCHAR NOT NULL,
                    
                    -- Foreign key references
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (store_id) REFERENCES shopify_stores(id)
                )
                """
                conn.execute(text(create_new_table_sql))
                logger.info("Created new archive table without age_checker_detected")
                
                # Copy existing data (excluding age_checker_detected)
                copy_data_sql = """
                INSERT INTO fraud_analyses_archive_new
                SELECT 
                    id, user_id, store_id, order_name, shopify_order_id,
                    is_first_time_customer, order_total, transaction_attempts_count,
                    customer_name, duplicate_within_7days, previous_order_delivery_status,
                    previous_order_total, current_order_total, shopify_fraud_risk_level,
                    customer_notes, billing_address_outside_us,
                    same_billing_shipping, shipping_state, additional_details,
                    current_order_delivery_status, days_since_last_delivery,
                    raw_shopify_data, duplicate_match_details, transaction_details,
                    risk_assessment_details, customer_order_history, delivery_analytics,
                    rule_triggered_ids, rule_processing_results,
                    analysis_timestamp, processing_time_seconds, analysis_version,
                    archived_at, archive_reason
                FROM fraud_analyses_archive
                """
                conn.execute(text(copy_data_sql))
                logger.info("Copied existing data to new table")
                
                # Drop old table
                conn.execute(text("DROP TABLE fraud_analyses_archive"))
                logger.info("Dropped old archive table")
                
                # Rename new table
                conn.execute(text("ALTER TABLE fraud_analyses_archive_new RENAME TO fraud_analyses_archive"))
                logger.info("Renamed new table to fraud_analyses_archive")
                
                # Recreate indexes
                logger.info("Recreating indexes...")
                
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_fraud_analyses_archive_archived_at 
                    ON fraud_analyses_archive(archived_at)
                """))
                
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_fraud_analyses_archive_reason 
                    ON fraud_analyses_archive(archive_reason)
                """))
                
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_fraud_analyses_archive_store_order 
                    ON fraud_analyses_archive(store_id, order_name)
                """))
                
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_fraud_analyses_archive_user 
                    ON fraud_analyses_archive(user_id)
                """))
                
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_fraud_analyses_archive_user_archived 
                    ON fraud_analyses_archive(user_id, archived_at)
                """))
                
                logger.info("Successfully removed age_checker_detected column from fraud_analyses_archive")
            else:
                logger.info("age_checker_detected column not found in fraud_analyses_archive table - nothing to do")
                
    except SQLAlchemyError as e:
        logger.error(f"Migration failed: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during migration: {str(e)}")
        raise

if __name__ == "__main__":
    run_migration()