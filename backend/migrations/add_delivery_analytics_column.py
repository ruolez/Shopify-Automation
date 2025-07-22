#!/usr/bin/env python3
"""
Migration script to add delivery_analytics column to fraud_analyses table.
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
    """Add delivery_analytics column to fraud_analyses table"""
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT COUNT(*) 
                FROM pragma_table_info('fraud_analyses') 
                WHERE name='delivery_analytics'
            """))
            
            if result.scalar() > 0:
                logger.info("Column 'delivery_analytics' already exists in fraud_analyses table")
                return
            
            # Add the new column
            logger.info("Adding delivery_analytics column to fraud_analyses table...")
            conn.execute(text("""
                ALTER TABLE fraud_analyses 
                ADD COLUMN delivery_analytics JSON
            """))
            conn.commit()
            
            logger.info("✅ Migration completed successfully!")
            
    except OperationalError as e:
        if "no such column" in str(e).lower() or "duplicate column" in str(e).lower():
            logger.warning(f"Column might already exist or table structure is different: {e}")
        else:
            logger.error(f"Migration failed: {e}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error during migration: {e}")
        raise

if __name__ == "__main__":
    run_migration()