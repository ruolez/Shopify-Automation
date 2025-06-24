#!/usr/bin/env python3
"""
Migration script to add delay_ms column to processing_rules table.

Run this script to update existing databases with the new column.
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from database import DATABASE_URL

def migrate():
    """Add delay_ms column to processing_rules table"""
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("""
            SELECT COUNT(*) 
            FROM pragma_table_info('processing_rules') 
            WHERE name='delay_ms'
        """))
        
        if result.scalar() == 0:
            # Add the column with default value
            conn.execute(text("""
                ALTER TABLE processing_rules 
                ADD COLUMN delay_ms INTEGER DEFAULT 10
            """))
            conn.commit()
            print("✓ Added delay_ms column to processing_rules table")
        else:
            print("✓ delay_ms column already exists")

if __name__ == "__main__":
    migrate()