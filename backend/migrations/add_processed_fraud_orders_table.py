#!/usr/bin/env python3
"""
Migration script to create processed_fraud_orders table for tracking which orders have been through fraud detection.
This prevents duplicate fraud analysis processing.
Run this script to update your database schema.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from database import DATABASE_URL
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Create processed_fraud_orders table for fraud detection deduplication"""
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # Start transaction for rollback capability
            trans = conn.begin()
            
            try:
                # Check if processed_fraud_orders table exists
                logger.info("Checking if processed_fraud_orders table exists...")
                result = conn.execute(text("""
                    SELECT COUNT(*) 
                    FROM sqlite_master 
                    WHERE type='table' AND name='processed_fraud_orders'
                """))
                
                if result.scalar() == 0:
                    logger.info("Creating processed_fraud_orders table...")
                    conn.execute(text("""
                        CREATE TABLE processed_fraud_orders (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            store_id INTEGER NOT NULL,
                            order_id VARCHAR NOT NULL,
                            fraud_analysis_id INTEGER,
                            rules_applied INTEGER DEFAULT 0,
                            processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY(store_id) REFERENCES shopify_stores (id),
                            FOREIGN KEY(fraud_analysis_id) REFERENCES fraud_analyses (id),
                            UNIQUE(store_id, order_id)
                        )
                    """))
                    
                    # Create indexes for better performance
                    logger.info("Creating indexes for processed_fraud_orders table...")
                    conn.execute(text("""
                        CREATE INDEX idx_processed_fraud_orders_store_id 
                        ON processed_fraud_orders(store_id)
                    """))
                    
                    conn.execute(text("""
                        CREATE INDEX idx_processed_fraud_orders_order_id 
                        ON processed_fraud_orders(order_id)
                    """))
                    
                    logger.info("✅ Created processed_fraud_orders table with indexes")
                    
                    # Optional: Populate the table with existing fraud analyses
                    logger.info("Checking for existing fraud analyses to populate processed_fraud_orders...")
                    existing_count = conn.execute(text("""
                        SELECT COUNT(*) FROM fraud_analyses
                    """)).scalar()
                    
                    if existing_count > 0:
                        logger.info(f"Found {existing_count} existing fraud analyses. Populating processed_fraud_orders...")
                        conn.execute(text("""
                            INSERT INTO processed_fraud_orders (store_id, order_id, fraud_analysis_id, rules_applied, processed_at)
                            SELECT 
                                fa.store_id,
                                fa.shopify_order_id,
                                fa.id,
                                CASE 
                                    WHEN fa.rule_triggered_ids IS NOT NULL 
                                    THEN json_array_length(fa.rule_triggered_ids)
                                    ELSE 0 
                                END,
                                fa.analysis_timestamp
                            FROM fraud_analyses fa
                            WHERE NOT EXISTS (
                                SELECT 1 FROM processed_fraud_orders pfo 
                                WHERE pfo.store_id = fa.store_id 
                                AND pfo.order_id = fa.shopify_order_id
                            )
                        """))
                        
                        inserted_count = conn.execute(text("""
                            SELECT COUNT(*) FROM processed_fraud_orders
                        """)).scalar()
                        
                        logger.info(f"✅ Populated processed_fraud_orders with {inserted_count} existing analyses")
                    else:
                        logger.info("No existing fraud analyses found, processed_fraud_orders table is empty")
                else:
                    logger.info("processed_fraud_orders table already exists")
                
                # Commit all changes
                trans.commit()
                logger.info("✅ Migration completed successfully!")
                
            except Exception as e:
                # Rollback transaction on any error
                trans.rollback()
                logger.error(f"Migration failed, rolling back: {e}")
                raise
                
    except OperationalError as e:
        if "no such table" in str(e).lower() or "duplicate column" in str(e).lower():
            logger.warning(f"Table/column might already exist or schema is different: {e}")
        else:
            logger.error(f"Migration failed: {e}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error during migration: {e}")
        raise

if __name__ == "__main__":
    run_migration()