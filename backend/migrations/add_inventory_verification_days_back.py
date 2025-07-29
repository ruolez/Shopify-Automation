#!/usr/bin/env python3
"""
Migration script to add inventory_verification_days_back column to settings table.

This migration adds a new column to store the number of days to look back
for inventory verification, with a default value of 5 days.
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from database import DATABASE_URL

def migrate():
    """Add inventory_verification_days_back column to settings table"""
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("""
            SELECT COUNT(*) 
            FROM pragma_table_info('settings') 
            WHERE name='inventory_verification_days_back'
        """))
        
        if result.scalar() == 0:
            # Add the column with default value
            conn.execute(text("""
                ALTER TABLE settings 
                ADD COLUMN inventory_verification_days_back INTEGER DEFAULT 5
            """))
            
            # Update any NULL values to the default
            conn.execute(text("""
                UPDATE settings 
                SET inventory_verification_days_back = 5 
                WHERE inventory_verification_days_back IS NULL
            """))
            
            conn.commit()
            print("✓ Added inventory_verification_days_back column to settings table")
        else:
            print("Column inventory_verification_days_back already exists")

if __name__ == "__main__":
    migrate()