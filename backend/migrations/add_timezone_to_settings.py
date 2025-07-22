#!/usr/bin/env python3
"""
Database migration: Add timezone and date_format columns to Settings table
Run this script to add timezone support to existing installations.
"""

import sqlite3
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    """Add timezone and date_format columns to Settings table"""
    
    # Find database file (check common locations)
    possible_db_paths = [
        'app.db',
        'data/app.db',
        '/app/data/app.db',
        './app.db',
        './data/app.db'
    ]
    
    db_path = None
    for path in possible_db_paths:
        if os.path.exists(path):
            db_path = path
            break
    
    if not db_path:
        logger.error("Could not find database file. Checked paths: %s", possible_db_paths)
        return False
    
    logger.info(f"Using database at: {db_path}")
    
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # First check if settings table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='settings'
        """)
        if not cursor.fetchone():
            logger.info("Settings table does not exist yet. This must be a fresh install.")
            logger.info("Table will be created with timezone columns by SQLAlchemy.")
            conn.close()
            return True
        
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(settings)")
        columns = [row[1] for row in cursor.fetchall()]
        
        needs_timezone = 'timezone' not in columns
        needs_date_format = 'date_format' not in columns
        
        if not needs_timezone and not needs_date_format:
            logger.info("Timezone columns already exist. Migration not needed.")
            conn.close()
            return True
        
        # Add timezone column if needed
        if needs_timezone:
            logger.info("Adding 'timezone' column to settings table...")
            cursor.execute('''
                ALTER TABLE settings 
                ADD COLUMN timezone TEXT DEFAULT 'UTC'
            ''')
            logger.info("✓ Added timezone column")
        
        # Add date_format column if needed
        if needs_date_format:
            logger.info("Adding 'date_format' column to settings table...")
            cursor.execute('''
                ALTER TABLE settings 
                ADD COLUMN date_format TEXT DEFAULT 'MMM d, yyyy HH:mm'
            ''')
            logger.info("✓ Added date_format column")
        
        # Update existing rows to have default values
        if needs_timezone or needs_date_format:
            cursor.execute('''
                UPDATE settings 
                SET timezone = COALESCE(timezone, 'UTC'),
                    date_format = COALESCE(date_format, 'MMM d, yyyy HH:mm')
                WHERE timezone IS NULL OR date_format IS NULL
            ''')
            logger.info("✓ Updated existing rows with default values")
        
        # Commit changes
        conn.commit()
        conn.close()
        
        logger.info("Migration completed successfully!")
        logger.info("Users can now configure their timezone and date format preferences in Settings.")
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    logger.info("Starting timezone settings migration...")
    logger.info("Backup your database before running this migration!")
    
    success = migrate_database()
    
    if success:
        logger.info("Migration completed successfully!")
        exit(0)
    else:
        logger.error("Migration failed!")
        exit(1)