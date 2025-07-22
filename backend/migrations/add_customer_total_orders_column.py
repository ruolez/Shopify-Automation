#!/usr/bin/env python3
"""
Add customer_total_orders column to fraud_analyses table.

This migration adds a new column to track the total number of orders
the customer has placed (including the current order).
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

def add_customer_total_orders_column():
    """Add customer_total_orders column to fraud_analyses table."""
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.begin() as conn:
            # Check if column already exists
            result = conn.execute(text(
                "SELECT COUNT(*) FROM pragma_table_info('fraud_analyses') WHERE name='customer_total_orders'"
            ))
            exists = result.scalar() > 0
            
            if exists:
                logger.info("Column 'customer_total_orders' already exists in fraud_analyses table")
                return True
            
            # Add the column
            logger.info("Adding 'customer_total_orders' column to fraud_analyses table...")
            conn.execute(text(
                "ALTER TABLE fraud_analyses ADD COLUMN customer_total_orders INTEGER"
            ))
            logger.info("Column 'customer_total_orders' added successfully")
            
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
    success = add_customer_total_orders_column()
    if success:
        logger.info("Migration completed successfully!")
    else:
        logger.error("Migration failed!")
        sys.exit(1)