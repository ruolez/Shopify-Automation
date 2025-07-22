#!/usr/bin/env python3
"""
Migration: Add duplicate_detection_days column to settings table
Date: 2025-07-14
Purpose: Allow users to configure the duplicate detection period for fraud analysis
"""

import sqlite3
import os
import sys

def migrate_add_duplicate_detection_days():
    """Add duplicate_detection_days column to settings table"""
    
    db_path = os.getenv('DATABASE_URL', 'sqlite:///./shopify_automation.db').replace('sqlite:///', '')
    
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(settings)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'duplicate_detection_days' in columns:
            print("✅ duplicate_detection_days column already exists")
            return True
            
        # Add the new column with default value
        print("🔄 Adding duplicate_detection_days column to settings table...")
        cursor.execute("""
            ALTER TABLE settings 
            ADD COLUMN duplicate_detection_days INTEGER DEFAULT 7
        """)
        
        # Commit the changes
        conn.commit()
        print("✅ Successfully added duplicate_detection_days column")
        
        # Verify the column was added
        cursor.execute("PRAGMA table_info(settings)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'duplicate_detection_days' in columns:
            print("✅ Column verification successful")
            return True
        else:
            print("❌ Column verification failed")
            return False
            
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        return False
        
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    success = migrate_add_duplicate_detection_days()
    sys.exit(0 if success else 1)