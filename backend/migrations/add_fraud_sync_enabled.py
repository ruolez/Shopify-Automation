#!/usr/bin/env python3
"""
Add fraud_sync_enabled column to Settings table
"""

import sqlite3
import sys
import os

# Add parent directory to path to import models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine

def run_migration():
    """Add fraud_sync_enabled column to Settings table"""
    
    # Get database path from SQLAlchemy engine
    db_path = engine.url.database
    
    print(f"Running migration on database: {db_path}")
    
    # Connect to the database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(settings)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'fraud_sync_enabled' in columns:
            print("Column 'fraud_sync_enabled' already exists in Settings table")
            return
        
        # Add the column with default value True
        cursor.execute("""
            ALTER TABLE settings 
            ADD COLUMN fraud_sync_enabled BOOLEAN DEFAULT 1
        """)
        
        # Update existing rows to have fraud_sync_enabled = True
        cursor.execute("""
            UPDATE settings 
            SET fraud_sync_enabled = 1 
            WHERE fraud_sync_enabled IS NULL
        """)
        
        conn.commit()
        print("Successfully added 'fraud_sync_enabled' column to Settings table")
        
    except Exception as e:
        print(f"Error running migration: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    run_migration()