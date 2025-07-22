"""
Shared utilities for database migrations
"""
import sqlite3
import logging

logger = logging.getLogger(__name__)

def is_fresh_install(cursor):
    """
    Check if this is a fresh installation by looking for core tables.
    Returns True if core tables don't exist (fresh install), False otherwise.
    """
    # Check for the users table - this is created first in a fresh install
    cursor.execute("""
        SELECT COUNT(*) FROM sqlite_master 
        WHERE type='table' AND name IN ('users', 'shopify_stores', 'processing_rules')
    """)
    table_count = cursor.fetchone()[0]
    
    # If we have less than 3 core tables, it's likely a fresh install
    if table_count < 3:
        logger.info("Detected fresh installation (core tables not found)")
        return True
    
    # Additional check - if settings table exists but has no rows, it's also fresh
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='settings'
    """)
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM settings")
        if cursor.fetchone()[0] == 0:
            logger.info("Detected fresh installation (settings table empty)")
            return True
    
    return False

def table_exists(cursor, table_name):
    """Check if a table exists in the database"""
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name=?
    """, (table_name,))
    return cursor.fetchone() is not None

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns