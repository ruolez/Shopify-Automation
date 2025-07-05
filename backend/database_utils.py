import os
import shutil
import sqlite3
from datetime import datetime
from typing import Optional, Tuple
import logging
from sqlalchemy.orm import Session
from database import SessionLocal
from models import ProcessingRule
import json

logger = logging.getLogger(__name__)

def validate_sqlite_file(file_path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if a file is a valid SQLite database.
    Returns (is_valid, error_message)
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            return False, "File does not exist"
        
        # Check file size (max 500MB for safety)
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return False, "File is empty"
        if file_size > 500 * 1024 * 1024:  # 500MB
            return False, "File is too large (max 500MB)"
        
        # Check SQLite header
        with open(file_path, 'rb') as f:
            header = f.read(16)
            if not header.startswith(b'SQLite format 3'):
                return False, "Not a valid SQLite database file"
        
        # Try to connect and run a simple query
        conn = sqlite3.connect(file_path)
        try:
            cursor = conn.cursor()
            # Check if essential tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'admin_users')")
            tables = cursor.fetchall()
            if len(tables) < 2:
                return False, "Database is missing essential tables"
            
            # Verify database integrity
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            if result[0] != 'ok':
                return False, "Database integrity check failed"
                
        finally:
            conn.close()
        
        return True, None
        
    except sqlite3.DatabaseError as e:
        return False, f"Database error: {str(e)}"
    except Exception as e:
        return False, f"Validation error: {str(e)}"

def create_backup(source_path: str, backup_dir: str = None) -> str:
    """
    Create a backup of the database file.
    Returns the path to the backup file.
    """
    if backup_dir is None:
        backup_dir = os.path.dirname(source_path)
    
    # Ensure backup directory exists
    os.makedirs(backup_dir, exist_ok=True)
    
    # Generate backup filename with timestamp
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"backup_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    # Copy the database file
    shutil.copy2(source_path, backup_path)
    logger.info(f"Created backup at: {backup_path}")
    
    return backup_path

def restore_database(source_path: str, target_path: str, create_pre_restore_backup: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Restore a database from a backup file.
    Returns (success, error_message)
    """
    try:
        # Validate the source file
        is_valid, error_msg = validate_sqlite_file(source_path)
        if not is_valid:
            return False, f"Invalid database file: {error_msg}"
        
        # Create a pre-restore backup if requested
        if create_pre_restore_backup and os.path.exists(target_path):
            backup_dir = os.path.join(os.path.dirname(target_path), 'pre_restore_backups')
            pre_restore_backup = create_backup(target_path, backup_dir)
            logger.info(f"Created pre-restore backup: {pre_restore_backup}")
        
        # Ensure target directory exists
        target_dir = os.path.dirname(target_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        
        # Copy the source file to target location
        shutil.copy2(source_path, target_path)
        logger.info(f"Database restored from {source_path} to {target_path}")
        
        # Verify the restored database
        is_valid, error_msg = validate_sqlite_file(target_path)
        if not is_valid:
            return False, f"Restored database validation failed: {error_msg}"
        
        return True, None
        
    except Exception as e:
        logger.error(f"Database restore failed: {str(e)}")
        return False, f"Restore failed: {str(e)}"

def get_database_info(db_path: str) -> dict:
    """
    Get information about the database file.
    """
    info = {
        "exists": os.path.exists(db_path),
        "size": 0,
        "size_mb": 0,
        "modified": None,
        "table_count": 0,
        "user_count": 0,
        "store_count": 0,
        "rule_count": 0
    }
    
    if not info["exists"]:
        return info
    
    try:
        # Get file stats
        stat = os.stat(db_path)
        info["size"] = stat.st_size
        info["size_mb"] = round(stat.st_size / (1024 * 1024), 2)
        info["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        
        # Get database stats
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            
            # Count tables
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            info["table_count"] = cursor.fetchone()[0]
            
            # Count users
            cursor.execute("SELECT COUNT(*) FROM users")
            info["user_count"] = cursor.fetchone()[0]
            
            # Count stores
            cursor.execute("SELECT COUNT(*) FROM shopify_stores")
            info["store_count"] = cursor.fetchone()[0]
            
            # Count rules
            cursor.execute("SELECT COUNT(*) FROM processing_rules")
            info["rule_count"] = cursor.fetchone()[0]
            
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"Error getting database info: {str(e)}")
    
    return info

def cleanup_old_backups(backup_dir: str, keep_count: int = 10):
    """
    Clean up old backup files, keeping only the most recent ones.
    """
    if not os.path.exists(backup_dir):
        return
    
    try:
        # Get all backup files
        backup_files = []
        for filename in os.listdir(backup_dir):
            if filename.startswith('backup_') and filename.endswith('.db'):
                file_path = os.path.join(backup_dir, filename)
                if os.path.isfile(file_path):
                    backup_files.append((file_path, os.path.getmtime(file_path)))
        
        # Sort by modification time (newest first)
        backup_files.sort(key=lambda x: x[1], reverse=True)
        
        # Remove old backups
        for file_path, _ in backup_files[keep_count:]:
            os.remove(file_path)
            logger.info(f"Removed old backup: {file_path}")
            
    except Exception as e:
        logger.error(f"Error cleaning up backups: {str(e)}")


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