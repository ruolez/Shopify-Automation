#!/usr/bin/env python3
"""
Check database schema version and migration status
"""

import os
import sys
import sqlite3
from datetime import datetime

# Add backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from run_all_migrations import MigrationRunner, MIGRATION_ORDER

def check_schema_version():
    """Check and display current schema version and migration status"""
    try:
        runner = MigrationRunner()
        
        print("=== Shopify Automation Database Schema Status ===")
        print()
        
        # Get applied migrations
        with sqlite3.connect(runner.db_path) as conn:
            cursor = conn.cursor()
            
            # Check if migration table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='schema_migrations'
            """)
            if not cursor.fetchone():
                print("❌ No migration tracking table found")
                print("   This database has not been migrated yet.")
                print()
                print("Pending migrations:")
                for migration in MIGRATION_ORDER:
                    print(f"  - {migration}")
                return
            
            # Get applied migrations with timestamps
            cursor.execute("""
                SELECT migration_name, applied_at 
                FROM schema_migrations 
                ORDER BY applied_at
            """)
            applied = cursor.fetchall()
        
        if applied:
            print("✅ Applied Migrations:")
            for name, timestamp in applied:
                print(f"   {name:<40} (applied: {timestamp})")
        else:
            print("❌ No migrations have been applied yet")
        
        print()
        
        # Check pending migrations
        pending = runner.get_pending_migrations()
        if pending:
            print(f"⚠️  Pending Migrations ({len(pending)}):")
            for migration in pending:
                print(f"   - {migration}")
            print()
            print("Run './install-prod.sh --keep-db' or 'python run_all_migrations.py' to apply them.")
        else:
            print("✅ Database schema is up to date!")
            print(f"   Total migrations: {len(MIGRATION_ORDER)}")
            print(f"   Latest migration: {MIGRATION_ORDER[-1] if MIGRATION_ORDER else 'None'}")
        
        print()
        print(f"Database location: {runner.db_path}")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    check_schema_version()