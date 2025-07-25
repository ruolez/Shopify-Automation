#!/usr/bin/env python3
"""
Migration to add inventory_verification_excluded_tag column to settings table
"""

import sys
import os
import logging
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, Column, String
from database import engine, get_db
from models import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Add inventory_verification_excluded_tag column to settings table"""
    
    with engine.connect() as conn:
        try:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT COUNT(*) 
                FROM pragma_table_info('settings') 
                WHERE name = 'inventory_verification_excluded_tag'
            """))
            
            if result.scalar() > 0:
                logger.info("Column 'inventory_verification_excluded_tag' already exists in settings table")
                return
            
            # Add the column
            logger.info("Adding 'inventory_verification_excluded_tag' column to settings table...")
            conn.execute(text("""
                ALTER TABLE settings 
                ADD COLUMN inventory_verification_excluded_tag VARCHAR(255)
            """))
            conn.commit()
            
            logger.info("Successfully added 'inventory_verification_excluded_tag' column to settings table")
            
            # Verify the column was added
            result = conn.execute(text("""
                SELECT COUNT(*) 
                FROM pragma_table_info('settings') 
                WHERE name = 'inventory_verification_excluded_tag'
            """))
            
            if result.scalar() > 0:
                logger.info("✓ Column verified successfully")
            else:
                logger.error("✗ Column verification failed")
                raise Exception("Column was not added successfully")
                
        except Exception as e:
            logger.error(f"Migration failed: {str(e)}")
            raise

if __name__ == "__main__":
    try:
        run_migration()
        logger.info("Migration completed successfully!")
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        sys.exit(1)