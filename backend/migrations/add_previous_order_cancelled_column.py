"""Add previous_order_cancelled column to fraud_analyses table"""

import logging
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError
import os
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Add previous_order_cancelled column to fraud_analyses table"""
    
    # Get database URL from environment or use default
    database_url = os.getenv('DATABASE_URL', 'sqlite:///./shopify_automation.db')
    
    # Create engine
    engine = create_engine(database_url)
    
    try:
        with engine.connect() as conn:
            # Start transaction
            trans = conn.begin()
            
            try:
                # Check if column already exists
                inspector = inspect(engine)
                columns = [col['name'] for col in inspector.get_columns('fraud_analyses')]
                
                if 'previous_order_cancelled' in columns:
                    logger.info("Column 'previous_order_cancelled' already exists in fraud_analyses table")
                    return True
                
                # Add the new column
                logger.info("Adding 'previous_order_cancelled' column to fraud_analyses table...")
                conn.execute(text("""
                    ALTER TABLE fraud_analyses 
                    ADD COLUMN previous_order_cancelled BOOLEAN
                """))
                
                logger.info("Successfully added 'previous_order_cancelled' column")
                
                # Commit transaction
                trans.commit()
                return True
                
            except Exception as e:
                # Rollback on error
                trans.rollback()
                logger.error(f"Error during migration: {str(e)}")
                raise
                
    except SQLAlchemyError as e:
        logger.error(f"Database error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return False


if __name__ == "__main__":
    logger.info(f"Starting migration at {datetime.now()}")
    
    success = run_migration()
    
    if success:
        logger.info("Migration completed successfully!")
    else:
        logger.error("Migration failed!")
        exit(1)