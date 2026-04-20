#!/usr/bin/env python3
"""
Migration script to create fraud_rule_stores join table for per-store fraud rule scoping.

Semantics: a fraud rule with zero rows in this table applies to ALL of the user's stores
(backward-compatible with the previous global behavior). One or more rows restricts the
rule to those specific stores.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from database import DATABASE_URL
from db_utils import check_table_exists, get_db_type
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            if check_table_exists(conn, 'fraud_rule_stores'):
                logger.info("fraud_rule_stores table already exists — nothing to do")
                trans.commit()
                return

            db_type = get_db_type()
            logger.info(f"Creating fraud_rule_stores table ({db_type})...")

            if db_type == "postgresql":
                conn.execute(text("""
                    CREATE TABLE fraud_rule_stores (
                        id SERIAL PRIMARY KEY,
                        fraud_rule_id INTEGER NOT NULL REFERENCES fraud_detection_rules(id) ON DELETE CASCADE,
                        store_id INTEGER NOT NULL REFERENCES shopify_stores(id) ON DELETE CASCADE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT unique_fraud_rule_store UNIQUE (fraud_rule_id, store_id)
                    )
                """))
                conn.execute(text("CREATE INDEX idx_fraud_rule_stores_rule ON fraud_rule_stores(fraud_rule_id)"))
                conn.execute(text("CREATE INDEX idx_fraud_rule_stores_store ON fraud_rule_stores(store_id)"))
            else:
                conn.execute(text("""
                    CREATE TABLE fraud_rule_stores (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fraud_rule_id INTEGER NOT NULL,
                        store_id INTEGER NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(fraud_rule_id) REFERENCES fraud_detection_rules(id) ON DELETE CASCADE,
                        FOREIGN KEY(store_id) REFERENCES shopify_stores(id) ON DELETE CASCADE,
                        CONSTRAINT unique_fraud_rule_store UNIQUE (fraud_rule_id, store_id)
                    )
                """))
                conn.execute(text("CREATE INDEX idx_fraud_rule_stores_rule ON fraud_rule_stores(fraud_rule_id)"))
                conn.execute(text("CREATE INDEX idx_fraud_rule_stores_store ON fraud_rule_stores(store_id)"))

            trans.commit()
            logger.info("✅ Created fraud_rule_stores table")
        except Exception as e:
            trans.rollback()
            logger.error(f"Migration failed, rolling back: {e}")
            raise


if __name__ == "__main__":
    run_migration()
