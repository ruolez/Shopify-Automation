"""
Add fraud_analyses_archive table for archiving fulfilled and cancelled orders.

This migration creates an archive table with the same structure as fraud_analyses
plus additional columns for archival metadata.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, Numeric, Index
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Create fraud_analyses_archive table"""
    # Get database URL from environment (required)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL environment variable is not set")
        raise ValueError("DATABASE_URL environment variable is required")
    engine = create_engine(database_url)
    
    try:
        with engine.begin() as conn:
            # Create the archive table with same structure as fraud_analyses
            # plus archive-specific columns
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS fraud_analyses_archive (
                -- Core identification (same as fraud_analyses)
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                store_id INTEGER NOT NULL,
                order_name VARCHAR NOT NULL,
                shopify_order_id VARCHAR NOT NULL,
                
                -- ALL 11 required fraud detection data points
                is_first_time_customer BOOLEAN,
                order_total NUMERIC(12, 2),
                transaction_attempts_count INTEGER,
                customer_name VARCHAR,
                duplicate_within_7days BOOLEAN,
                previous_order_delivery_status VARCHAR,
                previous_order_total NUMERIC(12, 2),
                current_order_total NUMERIC(12, 2),
                shopify_fraud_risk_level VARCHAR,
                age_checker_detected BOOLEAN,
                customer_notes TEXT,
                billing_address_outside_us BOOLEAN,
                same_billing_shipping BOOLEAN,
                shipping_state VARCHAR,
                additional_details TEXT,
                current_order_delivery_status VARCHAR,
                days_since_last_delivery INTEGER,
                
                -- Supporting data for analysis and fine-tuning
                raw_shopify_data TEXT,  -- JSON stored as TEXT in SQLite
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
                archive_reason VARCHAR NOT NULL,  -- 'order_fulfilled' or 'order_cancelled'
                
                -- Foreign key references (for data integrity)
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (store_id) REFERENCES shopify_stores(id)
            )
            """
            conn.execute(text(create_table_sql))
            
            # Create indexes for efficient querying
            logger.info("Creating indexes on fraud_analyses_archive table...")
            
            # Index on archived_at for time-based queries
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_fraud_analyses_archive_archived_at 
                ON fraud_analyses_archive(archived_at)
            """))
            
            # Index on archive_reason for filtering
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_fraud_analyses_archive_reason 
                ON fraud_analyses_archive(archive_reason)
            """))
            
            # Index on store_id and order_name for lookups
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_fraud_analyses_archive_store_order 
                ON fraud_analyses_archive(store_id, order_name)
            """))
            
            # Index on user_id for user-scoped queries
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_fraud_analyses_archive_user 
                ON fraud_analyses_archive(user_id)
            """))
            
            # Composite index for efficient filtering
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_fraud_analyses_archive_user_archived 
                ON fraud_analyses_archive(user_id, archived_at)
            """))
            
            logger.info("Successfully created fraud_analyses_archive table and indexes")
            
    except SQLAlchemyError as e:
        logger.error(f"Migration failed: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during migration: {str(e)}")
        raise

if __name__ == "__main__":
    run_migration()