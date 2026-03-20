import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import SessionLocal
from models import ProcessingRule

logger = logging.getLogger(__name__)

def get_database_info_postgres(db: Session) -> dict:
    """
    Get information about the PostgreSQL database.
    """
    info = {
        "exists": True,
        "size": 0,
        "size_mb": 0,
        "modified": None,
        "table_count": 0,
        "user_count": 0,
        "store_count": 0,
        "rule_count": 0
    }
    
    try:
        # Get database size
        result = db.execute(text("""
            SELECT pg_database_size(current_database()) as size,
                   pg_size_pretty(pg_database_size(current_database())) as size_pretty
        """))
        db_info = result.fetchone()
        if db_info:
            info["size"] = db_info.size
            info["size_mb"] = round(db_info.size / (1024 * 1024), 2)
        
        # Count tables
        result = db.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """))
        info["table_count"] = result.scalar() or 0
        
        # Count users
        result = db.execute(text("SELECT COUNT(*) FROM users"))
        info["user_count"] = result.scalar() or 0
        
        # Count stores
        result = db.execute(text("SELECT COUNT(*) FROM shopify_stores"))
        info["store_count"] = result.scalar() or 0
        
        # Count rules
        result = db.execute(text("SELECT COUNT(*) FROM processing_rules"))
        info["rule_count"] = result.scalar() or 0
        
    except Exception as e:
        logger.error(f"Error getting PostgreSQL database info: {str(e)}")
    
    return info

def migrate_rules_to_new_format():
    """
    Migrate existing rules from legacy array format to new object format with logical operator.
    Legacy format: [condition1, condition2, ...]
    New format: {"operator": "AND", "conditions": [condition1, condition2, ...]}
    """
    db: Session = SessionLocal()
    try:
        rules = db.query(ProcessingRule).all()
        migrated_count = 0
        
        for rule in rules:
            # Check if conditions need migration
            if isinstance(rule.conditions, list):
                # Legacy format detected - migrate to new format
                logger.info(f"Migrating rule '{rule.name}' (ID: {rule.id}) to new format")
                
                # Convert to new format (default to AND for backward compatibility)
                new_conditions = {
                    "operator": "AND",
                    "conditions": rule.conditions
                }
                
                rule.conditions = new_conditions
                migrated_count += 1
                
        if migrated_count > 0:
            db.commit()
            logger.info(f"Successfully migrated {migrated_count} rules to new format")
        else:
            logger.info("No rules needed migration - all rules are already in the new format")
            
    except Exception as e:
        logger.error(f"Error during rule migration: {str(e)}")
        db.rollback()
    finally:
        db.close()

