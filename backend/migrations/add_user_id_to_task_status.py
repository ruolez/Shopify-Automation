"""
Add user_id column to task_status table
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, Column, Integer, ForeignKey, text
from sqlalchemy.exc import OperationalError
from database import DATABASE_URL
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    engine = create_engine(DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # Check if user_id column already exists
            result = conn.execute(text("PRAGMA table_info(task_status)"))
            columns = [row[1] for row in result]
            
            if 'user_id' not in columns:
                logger.info("Adding user_id column to task_status table...")
                conn.execute(text("ALTER TABLE task_status ADD COLUMN user_id INTEGER REFERENCES users(id)"))
                conn.commit()
                logger.info("Successfully added user_id column to task_status table")
            else:
                logger.info("user_id column already exists in task_status table")
                
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise

if __name__ == "__main__":
    run_migration()