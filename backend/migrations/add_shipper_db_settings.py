#!/usr/bin/env python3
"""
Migration: add shipper database connection and default shipping amount to settings.

Used by the shipping-cost estimate in Order Profit. The password column holds a
Fernet-encrypted value (see models.Settings.shipper_db_password).
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from database import DATABASE_URL
import logging

logger = logging.getLogger(__name__)

COLUMNS = [
    ("shipper_db_host", "VARCHAR(255)"),
    ("shipper_db_port", "INTEGER DEFAULT 1433"),
    ("shipper_db_name", "VARCHAR(255)"),
    ("shipper_db_user", "VARCHAR(255)"),
    ("shipper_db_password", "TEXT"),
    ("default_shipping_amount", "NUMERIC(10,2) DEFAULT 0"),
    ("shipper_db_last_sync_at", "TIMESTAMPTZ"),
    ("shipper_db_last_error", "TEXT"),
]


def missing_columns(conn) -> list:
    existing = {
        row[0] for row in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'settings'"
        ))
    }
    return [(name, definition) for name, definition in COLUMNS if name not in existing]


def run_migration(engine=None, lock_timeout: str = "10s"):
    engine = engine or create_engine(DATABASE_URL)

    with engine.connect() as conn:
        missing = missing_columns(conn)
        conn.rollback()
        if not missing:
            logger.info("settings shipper database columns already present")
            return

        try:
            with conn.begin():
                # ALTER TABLE needs an exclusive lock; fail fast instead of queueing behind workers
                conn.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
                for name, definition in missing:
                    conn.execute(text(
                        f"ALTER TABLE settings ADD COLUMN IF NOT EXISTS {name} {definition}"
                    ))
                    logger.info(f"Added settings.{name}")
            logger.info("Shipper database settings migration complete")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
