#!/usr/bin/env python3
"""
Migration: Remove age_checker_detected column from fraud_analyses table

This migration removes the age_checker_detected column as we're replacing
it with a more flexible customer_notes contains condition.
"""

import os
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from database import engine
from sqlalchemy import text, inspect
from sqlalchemy.exc import OperationalError, ProgrammingError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_column_exists(connection, table_name, column_name):
    """Check if a column exists in a table."""
    try:
        inspector = inspect(connection)
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        return column_name in columns
    except Exception as e:
        logger.error(f"Error checking column existence: {e}")
        return False

def run_migration():
    """Run the migration to remove age_checker_detected column."""
    
    with engine.begin() as connection:
        try:
            # Check if the column exists before trying to drop it
            if check_column_exists(connection, 'fraud_analyses', 'age_checker_detected'):
                logger.info("Removing age_checker_detected column from fraud_analyses table...")
                
                # SQLite doesn't support DROP COLUMN directly, so we need to recreate the table
                # First, create a new table without the column
                connection.execute(text("""
                    CREATE TABLE fraud_analyses_new (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        store_id INTEGER NOT NULL,
                        order_name TEXT NOT NULL,
                        shopify_order_id TEXT NOT NULL,
                        analysis_timestamp DATETIME NOT NULL,
                        is_first_time_customer BOOLEAN,
                        order_total NUMERIC(12, 2),
                        transaction_attempts_count INTEGER,
                        customer_name TEXT,
                        previous_order_delivery_status TEXT,
                        previous_order_total NUMERIC(12, 2),
                        current_order_total NUMERIC(12, 2),
                        shopify_fraud_risk_level TEXT,
                        customer_notes TEXT,
                        billing_address_outside_us BOOLEAN,
                        same_billing_shipping BOOLEAN,
                        shipping_state TEXT,
                        additional_details TEXT,
                        current_order_delivery_status TEXT,
                        days_since_last_delivery INTEGER,
                        raw_shopify_data JSON,
                        duplicate_match_details JSON,
                        transaction_details JSON,
                        risk_assessment_details JSON,
                        customer_order_history JSON,
                        delivery_analytics JSON,
                        rule_triggered_ids JSON,
                        rule_processing_results JSON,
                        processing_time_seconds NUMERIC(8, 4),
                        analysis_version TEXT,
                        duplicate_within_7days BOOLEAN DEFAULT 0,
                        fraud_order_total_multiple NUMERIC(10, 2),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                        FOREIGN KEY (store_id) REFERENCES shopify_stores (id) ON DELETE CASCADE,
                        UNIQUE (store_id, order_name)
                    )
                """))
                
                # Copy data from old table to new table (excluding age_checker_detected)
                connection.execute(text("""
                    INSERT INTO fraud_analyses_new 
                    SELECT 
                        id, user_id, store_id, order_name, shopify_order_id, analysis_timestamp,
                        is_first_time_customer, order_total, transaction_attempts_count,
                        customer_name, previous_order_delivery_status, previous_order_total, 
                        current_order_total, shopify_fraud_risk_level, customer_notes,
                        billing_address_outside_us, same_billing_shipping, shipping_state,
                        additional_details, current_order_delivery_status, days_since_last_delivery,
                        raw_shopify_data, duplicate_match_details, transaction_details,
                        risk_assessment_details, customer_order_history, delivery_analytics,
                        rule_triggered_ids, rule_processing_results, processing_time_seconds,
                        analysis_version, duplicate_within_7days, 
                        CASE 
                            WHEN current_order_total IS NOT NULL AND previous_order_total IS NOT NULL 
                                AND previous_order_total > 0
                            THEN ROUND(CAST(current_order_total AS FLOAT) / CAST(previous_order_total AS FLOAT), 2)
                            ELSE NULL
                        END as fraud_order_total_multiple,
                        created_at, updated_at
                    FROM fraud_analyses
                """))
                
                # Drop the old table
                connection.execute(text("DROP TABLE fraud_analyses"))
                
                # Rename the new table to the original name
                connection.execute(text("ALTER TABLE fraud_analyses_new RENAME TO fraud_analyses"))
                
                logger.info("Successfully removed age_checker_detected column from fraud_analyses table")
            else:
                logger.info("Column age_checker_detected does not exist in fraud_analyses table, skipping...")
            
            # Also check and remove from fraud_analyses_archive if it exists
            try:
                inspector = inspect(connection)
                if 'fraud_analyses_archive' in inspector.get_table_names():
                    if check_column_exists(connection, 'fraud_analyses_archive', 'age_checker_detected'):
                        logger.info("Removing age_checker_detected column from fraud_analyses_archive table...")
                        
                        # Create new archive table without the column
                        connection.execute(text("""
                            CREATE TABLE fraud_analyses_archive_new (
                                id INTEGER PRIMARY KEY,
                                user_id INTEGER NOT NULL,
                                store_id INTEGER NOT NULL,
                                order_name TEXT NOT NULL,
                                shopify_order_id TEXT NOT NULL,
                                analysis_timestamp DATETIME NOT NULL,
                                is_first_time_customer BOOLEAN,
                                order_total NUMERIC(12, 2),
                                transaction_attempts_count INTEGER,
                                customer_name TEXT,
                                previous_order_delivery_status TEXT,
                                previous_order_total NUMERIC(12, 2),
                                current_order_total NUMERIC(12, 2),
                                shopify_fraud_risk_level TEXT,
                                customer_notes TEXT,
                                billing_address_outside_us BOOLEAN,
                                same_billing_shipping BOOLEAN,
                                shipping_state TEXT,
                                additional_details TEXT,
                                current_order_delivery_status TEXT,
                                days_since_last_delivery INTEGER,
                                raw_shopify_data JSON,
                                duplicate_match_details JSON,
                                transaction_details JSON,
                                risk_assessment_details JSON,
                                customer_order_history JSON,
                                delivery_analytics JSON,
                                rule_triggered_ids JSON,
                                rule_processing_results JSON,
                                processing_time_seconds NUMERIC(8, 4),
                                analysis_version TEXT,
                                duplicate_within_7days BOOLEAN DEFAULT 0,
                                fraud_order_total_multiple NUMERIC(10, 2),
                                created_at DATETIME,
                                updated_at DATETIME,
                                archived_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                                FOREIGN KEY (store_id) REFERENCES shopify_stores (id) ON DELETE CASCADE
                            )
                        """))
                        
                        # Copy data from old archive table to new archive table
                        connection.execute(text("""
                            INSERT INTO fraud_analyses_archive_new 
                            SELECT 
                                id, user_id, store_id, order_name, shopify_order_id, analysis_timestamp,
                                is_first_time_customer, order_total, transaction_attempts_count,
                                customer_name, previous_order_delivery_status, previous_order_total, 
                                current_order_total, shopify_fraud_risk_level, customer_notes,
                                billing_address_outside_us, same_billing_shipping, shipping_state,
                                additional_details, current_order_delivery_status, days_since_last_delivery,
                                raw_shopify_data, duplicate_match_details, transaction_details,
                                risk_assessment_details, customer_order_history, delivery_analytics,
                                rule_triggered_ids, rule_processing_results, processing_time_seconds,
                                analysis_version, duplicate_within_7days, fraud_order_total_multiple,
                                created_at, updated_at, archived_at
                            FROM fraud_analyses_archive
                        """))
                        
                        # Drop the old archive table
                        connection.execute(text("DROP TABLE fraud_analyses_archive"))
                        
                        # Rename the new archive table
                        connection.execute(text("ALTER TABLE fraud_analyses_archive_new RENAME TO fraud_analyses_archive"))
                        
                        logger.info("Successfully removed age_checker_detected column from fraud_analyses_archive table")
                    else:
                        logger.info("Column age_checker_detected does not exist in fraud_analyses_archive table")
            except Exception as e:
                logger.warning(f"Could not update fraud_analyses_archive table: {e}")
                
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise

if __name__ == "__main__":
    logger.info("Starting migration: Remove age_checker_detected column")
    run_migration()
    logger.info("Migration completed successfully!")