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


def run_migration(engine=None):
    engine = engine or create_engine(DATABASE_URL)

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            for name, definition in COLUMNS:
                conn.execute(text(
                    f"ALTER TABLE shopify_stores ADD COLUMN IF NOT EXISTS {name} {definition}"
                ))
                logger.info(f"Ensured shopify_stores.{name} exists")
            trans.commit()
            logger.info("OAuth store fields migration complete")
        except Exception as e:
            trans.rollback()
            logger.error(f"Migration failed: {e}")
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
