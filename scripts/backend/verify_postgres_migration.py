#!/usr/bin/env python3
"""
PostgreSQL Migration Verification Script
Verifies that the migration from SQLite to PostgreSQL was successful
"""

import os
import sys
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, List, Tuple, Any
import json
from tabulate import tabulate
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class MigrationVerifier:
    def __init__(self, sqlite_path: str, postgres_config: Dict[str, str]):
        """
        Initialize the migration verifier.
        
        Args:
            sqlite_path: Path to SQLite database
            postgres_config: PostgreSQL connection configuration
        """
        self.sqlite_path = sqlite_path
        self.postgres_config = postgres_config
        self.results = {
            'tables': {},
            'data_integrity': {},
            'performance': {},
            'issues': []
        }
    
    def connect_sqlite(self) -> sqlite3.Connection:
        """Connect to SQLite database."""
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def connect_postgres(self) -> psycopg2.extensions.connection:
        """Connect to PostgreSQL database."""
        return psycopg2.connect(
            **self.postgres_config,
            cursor_factory=RealDictCursor
        )
    
    def verify_table_structure(self) -> Dict[str, bool]:
        """Verify that all tables exist in PostgreSQL."""
        logger.info("Verifying table structure...")
        
        sqlite_conn = self.connect_sqlite()
        pg_conn = self.connect_postgres()
        
        try:
            # Get SQLite tables
            sqlite_cursor = sqlite_conn.cursor()
            sqlite_cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' 
                AND name NOT LIKE 'sqlite_%'
            """)
            sqlite_tables = {row['name'] for row in sqlite_cursor.fetchall()}
            
            # Get PostgreSQL tables
            pg_cursor = pg_conn.cursor()
            pg_cursor.execute("""
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public'
            """)
            pg_tables = {row['tablename'] for row in pg_cursor.fetchall()}
            
            # Compare tables
            results = {}
            for table in sqlite_tables:
                exists = table in pg_tables
                results[table] = exists
                if not exists:
                    self.results['issues'].append(f"Table '{table}' missing in PostgreSQL")
            
            # Check for extra tables in PostgreSQL
            extra_tables = pg_tables - sqlite_tables
            if extra_tables:
                logger.info(f"Extra tables in PostgreSQL: {extra_tables}")
            
            self.results['tables'] = results
            return results
            
        finally:
            sqlite_conn.close()
            pg_conn.close()
    
    def verify_row_counts(self) -> Dict[str, Dict[str, int]]:
        """Verify row counts match between databases."""
        logger.info("Verifying row counts...")
        
        sqlite_conn = self.connect_sqlite()
        pg_conn = self.connect_postgres()
        
        try:
            results = {}
            
            for table in self.results['tables']:
                if not self.results['tables'][table]:
                    continue
                
                # Get SQLite count
                sqlite_cursor = sqlite_conn.cursor()
                sqlite_cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
                sqlite_count = sqlite_cursor.fetchone()['count']
                
                # Get PostgreSQL count
                pg_cursor = pg_conn.cursor()
                pg_cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
                pg_count = pg_cursor.fetchone()['count']
                
                results[table] = {
                    'sqlite': sqlite_count,
                    'postgres': pg_count,
                    'match': sqlite_count == pg_count
                }
                
                if not results[table]['match']:
                    self.results['issues'].append(
                        f"Row count mismatch in '{table}': "
                        f"SQLite={sqlite_count}, PostgreSQL={pg_count}"
                    )
            
            self.results['data_integrity']['row_counts'] = results
            return results
            
        finally:
            sqlite_conn.close()
            pg_conn.close()
    
    def verify_data_samples(self, sample_size: int = 10) -> Dict[str, bool]:
        """Verify data integrity by sampling records."""
        logger.info("Verifying data samples...")
        
        sqlite_conn = self.connect_sqlite()
        pg_conn = self.connect_postgres()
        
        try:
            results = {}
            
            for table in self.results['tables']:
                if not self.results['tables'][table]:
                    continue
                
                # Skip empty tables
                if (self.results['data_integrity']['row_counts'][table]['sqlite'] == 0):
                    results[table] = True
                    continue
                
                # Get sample from SQLite
                sqlite_cursor = sqlite_conn.cursor()
                sqlite_cursor.execute(f"""
                    SELECT * FROM {table} 
                    ORDER BY RANDOM() 
                    LIMIT {sample_size}
                """)
                sqlite_samples = [dict(row) for row in sqlite_cursor.fetchall()]
                
                # Verify each sample exists in PostgreSQL
                pg_cursor = pg_conn.cursor()
                matches = 0
                
                for sample in sqlite_samples:
                    # Build WHERE clause based on primary key or unique fields
                    if 'id' in sample:
                        pg_cursor.execute(f"""
                            SELECT * FROM {table} 
                            WHERE id = %s
                        """, (sample['id'],))
                    else:
                        # Use first column as key
                        key = list(sample.keys())[0]
                        pg_cursor.execute(f"""
                            SELECT * FROM {table} 
                            WHERE {key} = %s
                        """, (sample[key],))
                    
                    pg_record = pg_cursor.fetchone()
                    if pg_record:
                        # Compare fields (handling type differences)
                        if self._records_match(sample, dict(pg_record)):
                            matches += 1
                
                results[table] = matches == len(sqlite_samples)
                
                if not results[table]:
                    self.results['issues'].append(
                        f"Data mismatch in '{table}': "
                        f"{matches}/{len(sqlite_samples)} samples matched"
                    )
            
            self.results['data_integrity']['samples'] = results
            return results
            
        finally:
            sqlite_conn.close()
            pg_conn.close()
    
    def _records_match(self, sqlite_record: Dict, pg_record: Dict) -> bool:
        """Compare two records handling type differences."""
        for key in sqlite_record:
            if key not in pg_record:
                return False
            
            sqlite_val = sqlite_record[key]
            pg_val = pg_record[key]
            
            # Handle None values
            if sqlite_val is None and pg_val is None:
                continue
            
            # Handle boolean conversion (SQLite uses 0/1)
            if isinstance(sqlite_val, int) and isinstance(pg_val, bool):
                if bool(sqlite_val) != pg_val:
                    return False
            # Handle datetime strings
            elif isinstance(sqlite_val, str) and isinstance(pg_val, datetime):
                try:
                    sqlite_dt = datetime.fromisoformat(sqlite_val.replace(' ', 'T'))
                    if sqlite_dt != pg_val.replace(tzinfo=None):
                        return False
                except:
                    return False
            # Handle JSON fields
            elif isinstance(pg_val, (dict, list)):
                try:
                    if json.loads(sqlite_val) != pg_val:
                        return False
                except:
                    return False
            # Default comparison
            elif sqlite_val != pg_val:
                return False
        
        return True
    
    def check_indexes(self) -> Dict[str, List[str]]:
        """Check that important indexes exist in PostgreSQL."""
        logger.info("Checking indexes...")
        
        pg_conn = self.connect_postgres()
        
        try:
            pg_cursor = pg_conn.cursor()
            
            # Get all indexes
            pg_cursor.execute("""
                SELECT 
                    tablename,
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                ORDER BY tablename, indexname
            """)
            
            indexes = {}
            for row in pg_cursor.fetchall():
                table = row['tablename']
                if table not in indexes:
                    indexes[table] = []
                indexes[table].append(row['indexname'])
            
            # Check for required indexes
            required_indexes = {
                'users': ['email'],
                'shopify_stores': ['user_id'],
                'processing_rules': ['user_id', 'priority'],
                'fraud_detection_rules': ['user_id', 'priority'],
                'order_logs': ['user_id', 'created_at'],
                'fraud_analyses': ['user_id', 'created_at']
            }
            
            missing_indexes = []
            for table, fields in required_indexes.items():
                if table in indexes:
                    table_indexes = ' '.join(indexes[table])
                    for field in fields:
                        if field not in table_indexes:
                            missing_indexes.append(f"{table}.{field}")
            
            if missing_indexes:
                self.results['issues'].append(
                    f"Missing indexes: {', '.join(missing_indexes)}"
                )
            
            self.results['performance']['indexes'] = indexes
            return indexes
            
        finally:
            pg_conn.close()
    
    def check_sequences(self) -> Dict[str, int]:
        """Check that sequences are properly set."""
        logger.info("Checking sequences...")
        
        pg_conn = self.connect_postgres()
        
        try:
            pg_cursor = pg_conn.cursor()
            
            # Get all sequences and their current values
            pg_cursor.execute("""
                SELECT 
                    schemaname,
                    sequencename,
                    last_value
                FROM pg_sequences
                WHERE schemaname = 'public'
            """)
            
            sequences = {}
            for row in pg_cursor.fetchall():
                sequences[row['sequencename']] = row['last_value']
            
            # Check that sequences are ahead of max IDs
            for table in self.results['tables']:
                if not self.results['tables'][table]:
                    continue
                
                # Check if table has an id column
                pg_cursor.execute(f"""
                    SELECT MAX(id) as max_id FROM {table}
                    WHERE EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = '{table}'
                        AND column_name = 'id'
                    )
                """)
                
                result = pg_cursor.fetchone()
                if result and result['max_id']:
                    seq_name = f"{table}_id_seq"
                    if seq_name in sequences:
                        if sequences[seq_name] < result['max_id']:
                            self.results['issues'].append(
                                f"Sequence '{seq_name}' is behind max ID: "
                                f"seq={sequences[seq_name]}, max={result['max_id']}"
                            )
            
            self.results['performance']['sequences'] = sequences
            return sequences
            
        finally:
            pg_conn.close()
    
    def run_full_verification(self) -> Dict[str, Any]:
        """Run complete verification suite."""
        print(f"\n{Colors.HEADER}{'='*60}")
        print("PostgreSQL Migration Verification")
        print(f"{'='*60}{Colors.ENDC}\n")
        
        # Check if databases exist
        if not os.path.exists(self.sqlite_path):
            print(f"{Colors.FAIL}✗ SQLite database not found: {self.sqlite_path}{Colors.ENDC}")
            return self.results
        
        # Run verifications
        steps = [
            ("Table Structure", self.verify_table_structure),
            ("Row Counts", self.verify_row_counts),
            ("Data Samples", self.verify_data_samples),
            ("Indexes", self.check_indexes),
            ("Sequences", self.check_sequences)
        ]
        
        for step_name, step_func in steps:
            print(f"{Colors.OKBLUE}Checking {step_name}...{Colors.ENDC}")
            try:
                step_func()
                print(f"{Colors.OKGREEN}✓ {step_name} checked{Colors.ENDC}")
            except Exception as e:
                print(f"{Colors.FAIL}✗ {step_name} failed: {e}{Colors.ENDC}")
                self.results['issues'].append(f"{step_name} check failed: {str(e)}")
        
        # Print summary
        self._print_summary()
        
        return self.results
    
    def _print_summary(self):
        """Print verification summary."""
        print(f"\n{Colors.HEADER}{'='*60}")
        print("Verification Summary")
        print(f"{'='*60}{Colors.ENDC}\n")
        
        # Table summary
        if 'tables' in self.results:
            table_data = []
            for table, exists in self.results['tables'].items():
                status = f"{Colors.OKGREEN}✓{Colors.ENDC}" if exists else f"{Colors.FAIL}✗{Colors.ENDC}"
                table_data.append([table, status])
            
            print(f"{Colors.BOLD}Tables:{Colors.ENDC}")
            print(tabulate(table_data, headers=['Table', 'Status'], tablefmt='grid'))
            print()
        
        # Row count summary
        if 'row_counts' in self.results.get('data_integrity', {}):
            count_data = []
            for table, counts in self.results['data_integrity']['row_counts'].items():
                status = f"{Colors.OKGREEN}✓{Colors.ENDC}" if counts['match'] else f"{Colors.FAIL}✗{Colors.ENDC}"
                count_data.append([
                    table,
                    counts['sqlite'],
                    counts['postgres'],
                    status
                ])
            
            print(f"{Colors.BOLD}Row Counts:{Colors.ENDC}")
            print(tabulate(
                count_data,
                headers=['Table', 'SQLite', 'PostgreSQL', 'Match'],
                tablefmt='grid'
            ))
            print()
        
        # Issues summary
        if self.results['issues']:
            print(f"{Colors.WARNING}Issues Found:{Colors.ENDC}")
            for issue in self.results['issues']:
                print(f"  {Colors.FAIL}• {issue}{Colors.ENDC}")
            print()
        else:
            print(f"{Colors.OKGREEN}✓ No issues found!{Colors.ENDC}\n")
        
        # Final verdict
        if not self.results['issues']:
            print(f"{Colors.OKGREEN}{Colors.BOLD}")
            print("🎉 Migration Verification PASSED!")
            print(f"All data successfully migrated to PostgreSQL.{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}{Colors.BOLD}")
            print("⚠️  Migration Verification FAILED!")
            print(f"Please review the issues above.{Colors.ENDC}")


def main():
    """Main verification function."""
    # Get configuration from environment or defaults
    sqlite_path = os.getenv('SQLITE_PATH', './app.db')
    
    postgres_config = {
        'dbname': os.getenv('POSTGRES_DB', 'shopify_db'),
        'user': os.getenv('POSTGRES_USER', 'shopify_user'),
        'password': os.getenv('POSTGRES_PASSWORD', 'changeme'),
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432')
    }
    
    # Create verifier and run verification
    verifier = MigrationVerifier(sqlite_path, postgres_config)
    results = verifier.run_full_verification()
    
    # Exit with appropriate code
    if results['issues']:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()