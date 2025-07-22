#!/usr/bin/env python3
"""
Add days_since_last_delivery column to fraud_analyses table.

This migration adds a new column to track the number of days between
the current order creation and the previous order's delivery date.
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

def add_days_since_last_delivery_column():
    """Add days_since_last_delivery column to fraud_analyses table."""
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.begin() as conn:
            # Check if column already exists
            result = conn.execute(text(
                "SELECT COUNT(*) FROM pragma_table_info('fraud_analyses') WHERE name='days_since_last_delivery'"
            ))
            exists = result.scalar() > 0
            
            if exists:
                logger.info("Column 'days_since_last_delivery' already exists in fraud_analyses table")
                return True
            
            # Add the column
            logger.info("Adding 'days_since_last_delivery' column to fraud_analyses table...")
            conn.execute(text(
                "ALTER TABLE fraud_analyses ADD COLUMN days_since_last_delivery INTEGER"
            ))
            logger.info("Column 'days_since_last_delivery' added successfully")
            
            return True
            
    except OperationalError as e:
        logger.error(f"Error adding column: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return False
    finally:
        engine.dispose()

if __name__ == "__main__":
    success = add_days_since_last_delivery_column()
    if success:
        logger.info("Migration completed successfully!")
    else:
        logger.error("Migration failed!")
        sys.exit(1)