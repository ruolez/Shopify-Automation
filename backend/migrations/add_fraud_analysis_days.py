#!/usr/bin/env python3
"""
Add fraud_analysis_days column to Settings table
"""
import sqlite3
import os
import sys
import logging

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrations.migration_utils import table_exists, column_exists

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    """Add fraud_analysis_days column to Settings table"""
    
    # Find database file
    possible_paths = [
        'app.db',
        'data/app.db',
        '/app/data/app.db',
        './app.db',
        './data/app.db'
    ]
    
    db_path = None
    for path in possible_paths:
        if os.path.exists(path):
            db_path = path
            break
    
    if not db_path:
        logger.error("Could not find database file")
        return False
    
    logger.info(f"Using database at: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if settings table exists
        if not table_exists(cursor, 'settings'):
            logger.info("Settings table does not exist yet. This must be a fresh install.")
            conn.close()
            return True
        
        # Check if column already exists
        if column_exists(cursor, 'settings', 'fraud_analysis_days'):
            logger.info("fraud_analysis_days column already exists")
            conn.close()
            return True
        
        # Add the column
        logger.info("Adding fraud_analysis_days column to settings table...")
        cursor.execute("""
            ALTER TABLE settings 
            ADD COLUMN fraud_analysis_days INTEGER DEFAULT 7
        """)
        
        # Update existing rows
        cursor.execute("""
            UPDATE settings 
            SET fraud_analysis_days = 7 
            WHERE fraud_analysis_days IS NULL
        """)
        
        conn.commit()
        conn.close()
        
        logger.info("Successfully added fraud_analysis_days column")
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    success = migrate_database()
    sys.exit(0 if success else 1)