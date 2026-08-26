#!/usr/bin/env python3
"""
Migration: add OAuth connection metadata to shopify_stores.

Adds columns for the Shopify OAuth authorization-code-grant flow while keeping
the existing manual admin-token path (auth_method="manual") the default.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from database import DATABASE_URL
import logging

logger = logging.getLogger(__name__)

COLUMNS = [
    ("auth_method", "VARCHAR DEFAULT 'manual' NOT NULL"),
    ("granted_scopes", "TEXT"),
    ("oauth_refresh_token", "TEXT"),
    ("token_expires_at", "TIMESTAMPTZ"),
    ("installed_at", "TIMESTAMPTZ"),
    ("needs_reauth", "BOOLEAN DEFAULT FALSE"),
]


def missing_columns(conn) -> list:
    existing = {
        row[0] for row in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'shopify_stores'"
        ))
    }
    return [(name, definition) for name, definition in COLUMNS if name not in existing]


def run_migration(engine=None, lock_timeout: str = "10s"):
    engine = engine or create_engine(DATABASE_URL)

    with engine.connect() as conn:
        missing = missing_columns(conn)
        conn.rollback()
        if not missing:
            logger.info("shopify_stores OAuth columns already present")
            return

        try:
            with conn.begin():
                # ALTER TABLE needs an exclusive lock; fail fast instead of queueing behind workers
                conn.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
                for name, definition in missing:
                    conn.execute(text(
                        f"ALTER TABLE shopify_stores ADD COLUMN IF NOT EXISTS {name} {definition}"
                    ))
                    logger.info(f"Added shopify_stores.{name}")
            logger.info("OAuth store fields migration complete")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
