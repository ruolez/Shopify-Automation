#!/usr/bin/env python3
"""
Migration Runner - Checks and applies database migrations via PostgreSQL.
"""

import importlib
import os
import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

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
    "add_fraud_rule_stores",
    "add_oauth_fields_to_stores",
]


def apply_migration(migration_name: str) -> bool:
    """Execute a migration module's run_migration(). Returns False if it has none."""
    try:
        module = importlib.import_module(f"migrations.{migration_name}")
    except ModuleNotFoundError:
        logger.warning(f"{migration_name} has no module (legacy entry); marking only")
        return False
    run = getattr(module, "run_migration", None)
    if run is None:
        logger.warning(f"{migration_name} has no run_migration(); marking only")
        return False
    run()
    return True


class MigrationRunner:
    def __init__(self):
        from sqlalchemy import create_engine, text
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL environment variable is not set")
        self.engine = create_engine(db_url)
        self.applied_migrations = set()
        self._ensure_migration_table()
        self._load_applied_migrations()

    def _ensure_migration_table(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    migration_name TEXT PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

    def _load_applied_migrations(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            result = conn.execute(text("SELECT migration_name FROM schema_migrations"))
            self.applied_migrations = {row[0] for row in result.fetchall()}

    def _mark_migration_applied(self, migration_name: str):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            conn.execute(
                text("INSERT INTO schema_migrations (migration_name, applied_at) VALUES (:name, :date) ON CONFLICT DO NOTHING"),
                {"name": migration_name, "date": datetime.now()}
            )
            conn.commit()

    def get_pending_migrations(self):
        return [m for m in MIGRATION_ORDER if m not in self.applied_migrations]

    def check_schema_compatibility(self) -> bool:
        pending = self.get_pending_migrations()
        if pending:
            logger.warning(f"Database needs {len(pending)} migrations:")
            for migration in pending:
                logger.warning(f"  - {migration}")
            return False
        logger.info("Database schema is up to date")
        return True

    def mark_all_applied(self):
        """Mark all migrations as applied (for fresh installs or post-restore)."""
        for migration in MIGRATION_ORDER:
            self._mark_migration_applied(migration)
        logger.info(f"Marked all {len(MIGRATION_ORDER)} migrations as applied")

    def apply_pending(self) -> int:
        pending = self.get_pending_migrations()
        for migration in pending:
            logger.info(f"Applying {migration}...")
            apply_migration(migration)
            self._mark_migration_applied(migration)
            self.applied_migrations.add(migration)
        return len(pending)


def main():
    logger.info("=== Shopify Automation Migration Runner ===")

    check_only = "--check" in sys.argv
    mark_all = "--mark-all" in sys.argv

    try:
        runner = MigrationRunner()

        if mark_all:
            runner.mark_all_applied()
            return 0

        if check_only:
            if runner.check_schema_compatibility():
                logger.info("No migrations needed")
                return 0
            else:
                logger.warning("Migrations are needed.")
                return 1
        else:
            pending = runner.get_pending_migrations()
            if not pending:
                logger.info("No pending migrations")
                return 0
            logger.info(f"Found {len(pending)} pending migrations")
            applied = runner.apply_pending()
            logger.info(f"Applied {applied} migrations")
            return 0

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
