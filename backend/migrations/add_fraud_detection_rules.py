#!/usr/bin/env python3
"""
Migration script to create fraud_detection_rules table and add rule tracking columns to fraud_analyses table.
Run this script to update your database schema.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from database import DATABASE_URL
from db_utils import check_table_exists, check_column_exists, get_db_type
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Create fraud_detection_rules table and add rule tracking columns to fraud_analyses table"""
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # Start transaction for rollback capability
            trans = conn.begin()
            
            try:
                # Step 1: Create fraud_detection_rules table
                logger.info("Checking if fraud_detection_rules table exists...")
                
                if not check_table_exists(conn, 'fraud_detection_rules'):
                    logger.info("Creating fraud_detection_rules table...")
                    db_type = get_db_type()
                    
                    if db_type == "postgresql":
                        conn.execute(text("""
                            CREATE TABLE fraud_detection_rules (
                                id SERIAL PRIMARY KEY,
                                user_id INTEGER NOT NULL,
                                name VARCHAR NOT NULL,
                                description TEXT,
                                conditions JSON NOT NULL,
                                actions JSON NOT NULL,
                                priority INTEGER DEFAULT 0,
                                delay_ms INTEGER DEFAULT 10,
                                is_active BOOLEAN DEFAULT true,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP,
                                FOREIGN KEY(user_id) REFERENCES users (id)
                            )
                        """))
                    else:
                        conn.execute(text("""
                            CREATE TABLE fraud_detection_rules (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_id INTEGER NOT NULL,
                                name VARCHAR NOT NULL,
                                description TEXT,
                                conditions JSON NOT NULL,
                                actions JSON NOT NULL,
                                priority INTEGER DEFAULT 0,
                                delay_ms INTEGER DEFAULT 10,
                                is_active BOOLEAN DEFAULT 1,
                                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME,
                                FOREIGN KEY(user_id) REFERENCES users (id)
                            )
                        """))
                    logger.info("✅ Created fraud_detection_rules table")
                else:
                    logger.info("fraud_detection_rules table already exists")
                
                # Step 2: Add rule_triggered_ids column to fraud_analyses
                logger.info("Checking if rule_triggered_ids column exists in fraud_analyses table...")
                
                if not check_column_exists(conn, 'fraud_analyses', 'rule_triggered_ids'):
                    logger.info("Adding rule_triggered_ids column to fraud_analyses table...")
                    conn.execute(text("""
                        ALTER TABLE fraud_analyses 
                        ADD COLUMN rule_triggered_ids JSON
                    """))
                    logger.info("✅ Added rule_triggered_ids column to fraud_analyses table")
                else:
                    logger.info("rule_triggered_ids column already exists in fraud_analyses table")
                
                # Step 3: Add rule_processing_results column to fraud_analyses
                logger.info("Checking if rule_processing_results column exists in fraud_analyses table...")
                
                if not check_column_exists(conn, 'fraud_analyses', 'rule_processing_results'):
                    logger.info("Adding rule_processing_results column to fraud_analyses table...")
                    conn.execute(text("""
                        ALTER TABLE fraud_analyses 
                        ADD COLUMN rule_processing_results JSON
                    """))
                    logger.info("✅ Added rule_processing_results column to fraud_analyses table")
                else:
                    logger.info("rule_processing_results column already exists in fraud_analyses table")
                
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