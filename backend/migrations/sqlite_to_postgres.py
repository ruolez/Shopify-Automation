#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script
Migrates all data from SQLite database to PostgreSQL
"""

import sqlite3
import psycopg2
from psycopg2.extras import execute_batch
import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database table order (respecting foreign key constraints)
TABLES_ORDER = [
    'users',
    'shopify_stores',
    'processing_rules',
    'fraud_detection_rules',
    'settings',
    'admin_users',
    'system_settings',
    'location_aliases',
    'location_mappings',
    'excluded_skus',
    'order_logs',
    'task_status',
    'processed_orders',
    'processed_fraud_orders',
    'out_of_stock_incidents',
    'admin_audit_logs',
    'fraud_analyses'
]

class DatabaseMigrator:
    def __init__(self, sqlite_path: str, postgres_config: Dict[str, str]):
        """
        Initialize the migrator with database connections.
        
        Args:
            sqlite_path: Path to SQLite database file
            postgres_config: PostgreSQL connection parameters
        """
        self.sqlite_path = sqlite_path
        self.postgres_config = postgres_config
        self.sqlite_conn = None
        self.pg_conn = None
        self.stats = {
            'tables_migrated': 0,
            'total_rows': 0,
            'errors': []
        }
    
    def connect(self):
        """Establish database connections."""
        try:
            # Connect to SQLite
            self.sqlite_conn = sqlite3.connect(self.sqlite_path)
            self.sqlite_conn.row_factory = sqlite3.Row
            logger.info(f"Connected to SQLite database: {self.sqlite_path}")
            
            # Connect to PostgreSQL
            self.pg_conn = psycopg2.connect(**self.postgres_config)
            self.pg_conn.autocommit = False
            logger.info("Connected to PostgreSQL database")
            
        except Exception as e:
            logger.error(f"Failed to connect to databases: {e}")
            raise
    
    def disconnect(self):
        """Close database connections."""
        if self.sqlite_conn:
            self.sqlite_conn.close()
        if self.pg_conn:
            self.pg_conn.close()
    
    def get_table_columns(self, table_name: str) -> List[str]:
        """Get column names for a table from SQLite."""
        cursor = self.sqlite_conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        return columns
    
    def convert_value(self, value: Any, column_type: str = None) -> Any:
        """
        Convert SQLite values to PostgreSQL compatible format.
        
        Args:
            value: The value to convert
            column_type: Optional column type hint
        
        Returns:
            Converted value
        """
        if value is None:
            return None
        
        # Convert SQLite boolean (0/1) to PostgreSQL boolean
        if column_type and 'bool' in column_type.lower():
            return bool(value) if value is not None else None
        
        # Convert datetime strings
        if isinstance(value, str) and column_type and 'timestamp' in column_type.lower():
            try:
                # Parse and format datetime
                if 'T' in value:
                    return value  # Already in ISO format
                else:
                    # Convert space-separated datetime
                    return value.replace(' ', 'T')
            except:
                return value
        
        # Handle JSON fields
        if column_type and 'json' in column_type.lower():
            if isinstance(value, str):
                try:
                    return json.dumps(json.loads(value))
                except:
                    return value
            else:
                return json.dumps(value) if value else None
        
        return value
    
    def get_column_types(self, table_name: str) -> Dict[str, str]:
        """Get PostgreSQL column types from information schema."""
        pg_cursor = self.pg_conn.cursor()
        query = """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = %s
            AND table_schema = 'public'
        """
        pg_cursor.execute(query, (table_name,))
        return {row[0]: row[1] for row in pg_cursor.fetchall()}
    
    def migrate_table(self, table_name: str) -> int:
        """
        Migrate a single table from SQLite to PostgreSQL.
        
        Args:
            table_name: Name of the table to migrate
        
        Returns:
            Number of rows migrated
        """
        logger.info(f"Migrating table: {table_name}")
        
        sqlite_cursor = self.sqlite_conn.cursor()
        pg_cursor = self.pg_conn.cursor()
        
        try:
            # Check if table exists in PostgreSQL
            pg_cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = %s
                )
            """, (table_name,))
            
            if not pg_cursor.fetchone()[0]:
                logger.warning(f"Table {table_name} does not exist in PostgreSQL, skipping")
                return 0
            
            # Get data from SQLite
            sqlite_cursor.execute(f"SELECT * FROM {table_name}")
            rows = sqlite_cursor.fetchall()
            
            if not rows:
                logger.info(f"No data in table {table_name}")
                return 0
            
            # Get column information
            columns = list(rows[0].keys())
            column_types = self.get_column_types(table_name)
            
            # Prepare insert query
            placeholders = ','.join(['%s'] * len(columns))
            insert_query = f"""
                INSERT INTO {table_name} ({','.join(columns)})
                VALUES ({placeholders})
                ON CONFLICT DO NOTHING
            """
            
            # Convert rows to tuples with type conversion
            data = []
            for row in rows:
                converted_row = []
                for col in columns:
                    value = row[col]
                    col_type = column_types.get(col, '')
                    converted_value = self.convert_value(value, col_type)
                    converted_row.append(converted_value)
                data.append(tuple(converted_row))
            
            # Batch insert
            execute_batch(pg_cursor, insert_query, data, page_size=1000)
            
            # Get actual number of inserted rows
            pg_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = pg_cursor.fetchone()[0]
            
            logger.info(f"Migrated {len(rows)} rows to {table_name} (total in table: {count})")
            return len(rows)
            
        except Exception as e:
            logger.error(f"Error migrating table {table_name}: {e}")
            self.stats['errors'].append(f"{table_name}: {str(e)}")
            raise
    
    def update_sequences(self):
        """Update PostgreSQL sequences for auto-increment columns."""
        logger.info("Updating sequences...")
        pg_cursor = self.pg_conn.cursor()
        
        for table in TABLES_ORDER:
            try:
                # Check if table has an id column with a sequence
                pg_cursor.execute(f"""
                    SELECT column_default 
                    FROM information_schema.columns 
                    WHERE table_name = %s 
                    AND column_name = 'id'
                    AND column_default LIKE 'nextval%%'
                """, (table,))
                
                result = pg_cursor.fetchone()
                if result:
                    # Update the sequence
                    pg_cursor.execute(f"""
                        SELECT setval(
                            pg_get_serial_sequence('{table}', 'id'),
                            COALESCE((SELECT MAX(id) FROM {table}), 1)
                        )
                    """)
                    logger.info(f"Updated sequence for {table}")
                    
            except Exception as e:
                logger.warning(f"Could not update sequence for {table}: {e}")
    
    def verify_migration(self) -> Dict[str, Dict[str, int]]:
        """
        Verify the migration by comparing row counts.
        
        Returns:
            Dictionary with table names and row counts
        """
        logger.info("Verifying migration...")
        
        sqlite_cursor = self.sqlite_conn.cursor()
        pg_cursor = self.pg_conn.cursor()
        
        verification = {}
        
        for table in TABLES_ORDER:
            try:
                # Get SQLite count
                sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table}")
                sqlite_count = sqlite_cursor.fetchone()[0]
                
                # Get PostgreSQL count
                pg_cursor.execute(f"SELECT COUNT(*) FROM {table}")
                pg_count = pg_cursor.fetchone()[0]
                
                verification[table] = {
                    'sqlite': sqlite_count,
                    'postgres': pg_count,
                    'match': sqlite_count == pg_count
                }
                
                if not verification[table]['match']:
                    logger.warning(
                        f"Row count mismatch in {table}: "
                        f"SQLite={sqlite_count}, PostgreSQL={pg_count}"
                    )
                
            except Exception as e:
                logger.error(f"Error verifying table {table}: {e}")
                verification[table] = {'error': str(e)}
        
        return verification
    
    def migrate(self, verify: bool = True) -> Dict[str, Any]:
        """
        Run the complete migration process.
        
        Args:
            verify: Whether to verify the migration after completion
        
        Returns:
            Migration statistics
        """
        start_time = datetime.now()
        
        try:
            self.connect()
            
            # Begin transaction
            self.pg_conn.autocommit = False
            
            # Migrate each table
            for table in TABLES_ORDER:
                try:
                    rows = self.migrate_table(table)
                    self.stats['tables_migrated'] += 1
                    self.stats['total_rows'] += rows
                except Exception as e:
                    logger.error(f"Failed to migrate {table}: {e}")
                    # Continue with other tables
            
            # Update sequences
            self.update_sequences()
            
            # Commit the transaction
            self.pg_conn.commit()
            logger.info("Migration transaction committed successfully")
            
            # Verify if requested
            if verify:
                self.stats['verification'] = self.verify_migration()
            
            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()
            self.stats['duration_seconds'] = duration
            
            logger.info(f"Migration completed in {duration:.2f} seconds")
            logger.info(f"Tables migrated: {self.stats['tables_migrated']}")
            logger.info(f"Total rows: {self.stats['total_rows']}")
            
            if self.stats['errors']:
                logger.warning(f"Errors encountered: {len(self.stats['errors'])}")
                for error in self.stats['errors']:
                    logger.warning(f"  - {error}")
            
            return self.stats
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            if self.pg_conn:
                self.pg_conn.rollback()
            raise
        
        finally:
            self.disconnect()


def main():
    """Main migration function."""
    # Get configuration from environment or use defaults
    sqlite_path = os.getenv('SQLITE_PATH', './app.db')
    
    postgres_config = {
        'dbname': os.getenv('POSTGRES_DB', 'shopify_db'),
        'user': os.getenv('POSTGRES_USER', 'shopify_user'),
        'password': os.getenv('POSTGRES_PASSWORD', 'changeme'),
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432')
    }
    
    # Check if SQLite database exists
    if not os.path.exists(sqlite_path):
        logger.error(f"SQLite database not found: {sqlite_path}")
        sys.exit(1)
    
    # Create migrator and run migration
    migrator = DatabaseMigrator(sqlite_path, postgres_config)
    
    try:
        stats = migrator.migrate(verify=True)
        
        # Print summary
        print("\n" + "="*50)
        print("MIGRATION SUMMARY")
        print("="*50)
        print(f"Duration: {stats['duration_seconds']:.2f} seconds")
        print(f"Tables migrated: {stats['tables_migrated']}")
        print(f"Total rows: {stats['total_rows']}")
        
        if 'verification' in stats:
            print("\nVerification Results:")
            all_match = True
            for table, counts in stats['verification'].items():
                if 'error' in counts:
                    print(f"  {table}: ERROR - {counts['error']}")
                    all_match = False
                else:
                    status = "✓" if counts['match'] else "✗"
                    print(f"  {status} {table}: SQLite={counts['sqlite']}, PostgreSQL={counts['postgres']}")
                    if not counts['match']:
                        all_match = False
            
            if all_match:
                print("\n✓ All tables migrated successfully!")
            else:
                print("\n⚠ Some tables have mismatched row counts. Please review.")
        
        if stats['errors']:
            print(f"\n⚠ {len(stats['errors'])} errors encountered during migration")
            sys.exit(1)
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()