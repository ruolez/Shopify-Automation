#!/usr/bin/env python3
"""Add reconciliation_batch_size column to settings table"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import text
from database import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_reconciliation_batch_size_column():
    """Add reconciliation_batch_size column to settings table"""
    try:
        with engine.connect() as connection:
            # Check if column already exists
            result = connection.execute(text("""
                SELECT COUNT(*) 
                FROM pragma_table_info('settings') 
                WHERE name = 'reconciliation_batch_size'
            """))
            
            if result.scalar() > 0:
                logger.info("reconciliation_batch_size column already exists")
                return True
            
            # Add the column with default value of 500
            logger.info("Adding reconciliation_batch_size column to settings table...")
            connection.execute(text("""
                ALTER TABLE settings 
                ADD COLUMN reconciliation_batch_size INTEGER DEFAULT 500
            """))
            connection.commit()
            
            logger.info("Successfully added reconciliation_batch_size column")
            return True
            
    except Exception as e:
        logger.error(f"Error adding reconciliation_batch_size column: {str(e)}")
        return False

if __name__ == "__main__":
    if add_reconciliation_batch_size_column():
        print("Migration completed successfully")
    else:
        print("Migration failed")
        sys.exit(1)