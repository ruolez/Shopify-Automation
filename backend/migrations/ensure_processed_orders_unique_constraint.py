#!/usr/bin/env python3
"""
Migration script to ensure the unique constraint exists on processed_orders table.

This constraint is critical for preventing race conditions in order processing.
The constraint should already exist from the model definition, but this migration
ensures it exists in databases that may have been created before the constraint
was added or where it was accidentally removed.

Run this script to verify/add the unique constraint.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from database import DATABASE_URL
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Ensure unique constraint exists on processed_orders(store_id, order_id)"""
    engine = create_engine(DATABASE_URL)

    try:
        with engine.connect() as conn:
            trans = conn.begin()

            try:
                # Check if we're using PostgreSQL or SQLite
                is_postgres = 'postgresql' in DATABASE_URL.lower()

                if is_postgres:
                    # PostgreSQL: Check if constraint exists
                    result = conn.execute(text("""
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE table_name = 'processed_orders'
                        AND constraint_type = 'UNIQUE'
                        AND constraint_name = 'unique_store_order'
                    """))
                    constraint_exists = result.fetchone() is not None

                    if not constraint_exists:
                        logger.info("Creating unique constraint on processed_orders(store_id, order_id)...")

                        # First, check for and remove any duplicates
                        dup_check = conn.execute(text("""
                            SELECT store_id, order_id, COUNT(*) as cnt
                            FROM processed_orders
                            GROUP BY store_id, order_id
                            HAVING COUNT(*) > 1
                        """))
                        duplicates = dup_check.fetchall()

                        if duplicates:
                            logger.warning(f"Found {len(duplicates)} duplicate entries, removing older ones...")
                            for dup in duplicates:
                                # Keep the newest record, delete older ones
                                conn.execute(text("""
                                    DELETE FROM processed_orders
                                    WHERE id NOT IN (
                                        SELECT MAX(id) FROM processed_orders
                                        WHERE store_id = :store_id AND order_id = :order_id
                                    )
                                    AND store_id = :store_id AND order_id = :order_id
                                """), {"store_id": dup[0], "order_id": dup[1]})
                            logger.info("Removed duplicate entries")

                        # Now create the constraint
                        conn.execute(text("""
                            ALTER TABLE processed_orders
                            ADD CONSTRAINT unique_store_order UNIQUE (store_id, order_id)
                        """))
                        logger.info("Created unique constraint 'unique_store_order'")
                    else:
                        logger.info("Unique constraint 'unique_store_order' already exists")

                    # Also create an index for better performance if it doesn't exist
                    idx_result = conn.execute(text("""
                        SELECT indexname
                        FROM pg_indexes
                        WHERE tablename = 'processed_orders'
                        AND indexname = 'idx_processed_orders_store_order'
                    """))
                    if idx_result.fetchone() is None:
                        logger.info("Creating index on processed_orders(store_id, order_id)...")
                        conn.execute(text("""
                            CREATE INDEX IF NOT EXISTS idx_processed_orders_store_order
                            ON processed_orders(store_id, order_id)
                        """))
                        logger.info("Created index 'idx_processed_orders_store_order'")
                    else:
                        logger.info("Index 'idx_processed_orders_store_order' already exists")

                else:
                    # SQLite: Check if constraint exists (via unique index)
                    result = conn.execute(text("""
                        SELECT name FROM sqlite_master
                        WHERE type='index'
                        AND tbl_name='processed_orders'
                        AND sql LIKE '%UNIQUE%'
                    """))
                    indexes = result.fetchall()
                    constraint_exists = any('store_id' in str(idx) and 'order_id' in str(idx) for idx in indexes)

                    if not constraint_exists:
                        logger.info("Creating unique index on processed_orders(store_id, order_id)...")

                        # First check for duplicates
                        dup_check = conn.execute(text("""
                            SELECT store_id, order_id, COUNT(*) as cnt
                            FROM processed_orders
                            GROUP BY store_id, order_id
                            HAVING COUNT(*) > 1
                        """))
                        duplicates = dup_check.fetchall()

                        if duplicates:
                            logger.warning(f"Found {len(duplicates)} duplicate entries, removing older ones...")
                            for dup in duplicates:
                                conn.execute(text("""
                                    DELETE FROM processed_orders
                                    WHERE rowid NOT IN (
                                        SELECT MAX(rowid) FROM processed_orders
                                        WHERE store_id = :store_id AND order_id = :order_id
                                    )
                                    AND store_id = :store_id AND order_id = :order_id
                                """), {"store_id": dup[0], "order_id": dup[1]})
                            logger.info("Removed duplicate entries")

                        # Create unique index (SQLite uses indexes for uniqueness)
                        conn.execute(text("""
                            CREATE UNIQUE INDEX IF NOT EXISTS unique_store_order
                            ON processed_orders(store_id, order_id)
                        """))
                        logger.info("Created unique index 'unique_store_order'")
                    else:
                        logger.info("Unique constraint already exists on processed_orders")

                trans.commit()
                logger.info("Migration completed successfully!")

            except Exception as e:
                trans.rollback()
                logger.error(f"Migration failed, rolling back: {e}")
                raise

    except OperationalError as e:
        if "already exists" in str(e).lower():
            logger.info("Constraint or index already exists")
        else:
            logger.error(f"Migration failed: {e}")
            raise
    except ProgrammingError as e:
        if "already exists" in str(e).lower():
            logger.info("Constraint or index already exists")
        else:
            logger.error(f"Migration failed: {e}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error during migration: {e}")
        raise


if __name__ == "__main__":
    run_migration()
