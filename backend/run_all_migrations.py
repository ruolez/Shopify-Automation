#!/usr/bin/env python3
"""
Migration Runner - Applies all database migrations in order
This script detects and runs any pending migrations for the Shopify Automation system.
"""

import os
import sys
import sqlite3
import importlib.util
import logging
from datetime import datetime
from typing import List, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Migration order (add new migrations at the end)
MIGRATION_ORDER = [
    "add_delay_ms_to_rules",
    "add_timezone_to_settings",
    "add_fraud_sync_enabled",
    "add_fraud_detection_rules",
    "add_duplicate_detection_days_column",
    "add_fraud_sync_days_column",
    "add_delivery_analytics_column",
    "add_days_since_last_delivery_column",
    "add_user_id_to_task_status",
    "add_fraud_analyses_archive",
    "remove_age_checker_from_archive",
]

# Special function name mappings for non-standard migrations
MIGRATION_FUNCTION_OVERRIDES = {
    "add_delay_ms_to_rules": "migrate",
    "add_duplicate_detection_days_column": "migrate_add_duplicate_detection_days",
    "add_fraud_sync_days_column": "migrate_add_fraud_sync_days",
    "add_days_since_last_delivery_column": "add_days_since_last_delivery_column",
}

class MigrationRunner:
    def __init__(self, db_path=None):
        self.db_path = db_path or self._find_database()
        self.applied_migrations = set()
        self._ensure_migration_table()
        self._load_applied_migrations()
    
    def _find_database(self):
        """Find the database file in common locations"""
        possible_paths = [
            'app.db',
            'data/app.db',
            '/app/data/app.db',
            './app.db',
            './data/app.db',
            'app/data/app.db'  # Docker volume path
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                logger.info(f"Found database at: {path}")
                return path
        
        raise FileNotFoundError(f"Could not find database. Checked: {possible_paths}")
    
    def _ensure_migration_table(self):
        """Create migration tracking table if it doesn't exist"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    migration_name TEXT PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
    
    def _load_applied_migrations(self):
        """Load list of already applied migrations"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT migration_name FROM schema_migrations')
            self.applied_migrations = {row[0] for row in cursor.fetchall()}
    
    def _mark_migration_applied(self, migration_name: str):
        """Mark a migration as applied"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO schema_migrations (migration_name) VALUES (?)',
                (migration_name,)
            )
            conn.commit()
    
    def _load_migration_module(self, migration_name: str):
        """Dynamically load a migration module"""
        migration_path = os.path.join(
            os.path.dirname(__file__), 
            'migrations', 
            f'{migration_name}.py'
        )
        
        if not os.path.exists(migration_path):
            logger.warning(f"Migration file not found: {migration_path}")
            return None
        
        spec = importlib.util.spec_from_file_location(migration_name, migration_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    
    def _run_single_migration(self, migration_name: str) -> bool:
        """Run a single migration"""
        logger.info(f"Running migration: {migration_name}")
        
        try:
            # Load the migration module
            module = self._load_migration_module(migration_name)
            if not module:
                return False
            
            # Look for migration function with overrides
            migration_func = None
            
            # Check for special function name override
            if migration_name in MIGRATION_FUNCTION_OVERRIDES:
                func_name = MIGRATION_FUNCTION_OVERRIDES[migration_name]
                if hasattr(module, func_name):
                    migration_func = getattr(module, func_name)
                else:
                    logger.error(f"Override function '{func_name}' not found in {migration_name}")
            else:
                # Standard function names
                if hasattr(module, 'migrate_database'):
                    migration_func = module.migrate_database
                elif hasattr(module, 'run_migration'):
                    migration_func = module.run_migration
            
            if migration_func:
                # Override the database path in the module if needed
                if hasattr(module, 'db_path'):
                    module.db_path = self.db_path
                
                # Run the migration
                result = migration_func()
                # Handle both boolean return and None/exception as success
                success = result is True or (result is None)
                if success:
                    self._mark_migration_applied(migration_name)
                    logger.info(f"✓ Migration {migration_name} completed successfully")
                    return True
                else:
                    logger.error(f"✗ Migration {migration_name} failed")
                    return False
            else:
                if migration_name in MIGRATION_FUNCTION_OVERRIDES:
                    logger.warning(f"Migration {migration_name} missing expected function: {MIGRATION_FUNCTION_OVERRIDES[migration_name]}")
                else:
                    logger.warning(f"Migration {migration_name} has no migrate_database or run_migration function")
                return False
                
        except Exception as e:
            logger.error(f"Error running migration {migration_name}: {str(e)}")
            return False
    
    def get_pending_migrations(self) -> List[str]:
        """Get list of migrations that haven't been applied yet"""
        return [m for m in MIGRATION_ORDER if m not in self.applied_migrations]
    
    def run_all_migrations(self) -> Tuple[int, int]:
        """Run all pending migrations"""
        pending = self.get_pending_migrations()
        
        if not pending:
            logger.info("No pending migrations found")
            return (0, 0)
        
        logger.info(f"Found {len(pending)} pending migrations")
        
        success_count = 0
        for migration_name in pending:
            if self._run_single_migration(migration_name):
                success_count += 1
            else:
                # Stop on first failure
                logger.error(f"Migration {migration_name} failed. Stopping migration process.")
                break
        
        return (success_count, len(pending) - success_count)
    
    def check_schema_compatibility(self) -> bool:
        """Check if the current database schema needs migrations"""
        pending = self.get_pending_migrations()
        
        if pending:
            logger.warning(f"Database needs {len(pending)} migrations:")
            for migration in pending:
                logger.warning(f"  - {migration}")
            return False
        else:
            logger.info("Database schema is up to date")
            return True


def main():
    """Main entry point for migration runner"""
    logger.info("=== Shopify Automation Migration Runner ===")
    
    # Parse command line arguments
    check_only = '--check' in sys.argv
    
    try:
        runner = MigrationRunner()
        
        if check_only:
            # Just check if migrations are needed
            if runner.check_schema_compatibility():
                logger.info("No migrations needed")
                return 0
            else:
                logger.warning("Migrations are needed. Run without --check to apply them.")
                return 1
        else:
            # Run migrations
            logger.info("Checking for pending migrations...")
            success, failed = runner.run_all_migrations()
            
            if failed > 0:
                logger.error(f"Migration process completed with errors: {success} succeeded, {failed} failed")
                return 1
            else:
                logger.info(f"All migrations completed successfully: {success} migrations applied")
                return 0
                
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())