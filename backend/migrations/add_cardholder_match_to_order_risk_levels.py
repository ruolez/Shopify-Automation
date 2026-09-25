#!/usr/bin/env python3
"""
Migration: add the cardholder name check to order_risk_levels.

cardholder_match holds MATCH / LAST_NAME_ONLY / MISMATCH / NONE for the Orders page
filter; existing rows stay NULL so the risk refresh task backfills them.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from database import DATABASE_URL
import logging

logger = logging.getLogger(__name__)

COLUMNS = [
    ("cardholder_match", "VARCHAR(20)"),
    ("cardholder_name", "VARCHAR(255)"),
]


def missing_columns(conn) -> list:
    existing = {
        row[0] for row in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'order_risk_levels'"
        ))
    }
    return [(name, definition) for name, definition in COLUMNS if name not in existing]


def run_migration(engine=None, lock_timeout: str = "10s"):
    engine = engine or create_engine(DATABASE_URL)

    with engine.connect() as conn:
        missing = missing_columns(conn)
        conn.rollback()
        if not missing:
            logger.info("order_risk_levels cardholder columns already present")
            return

        try:
            with conn.begin():
                # ALTER TABLE needs an exclusive lock; fail fast instead of queueing behind workers
                conn.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
                for name, definition in missing:
                    conn.execute(text(
                        f"ALTER TABLE order_risk_levels ADD COLUMN IF NOT EXISTS {name} {definition}"
                    ))
                    logger.info(f"Added order_risk_levels.{name}")
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_order_risk_levels_cardholder_match "
                    "ON order_risk_levels (cardholder_match)"
                ))
            logger.info("Order risk cardholder migration complete")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
