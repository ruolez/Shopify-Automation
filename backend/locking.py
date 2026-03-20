"""
Database-level locking utilities to prevent race conditions in order processing.

This module provides utilities for acquiring database locks to prevent TOCTOU
(Time-of-check to Time-of-use) race conditions when multiple Celery workers
process orders simultaneously.
"""

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, IntegrityError
from contextlib import contextmanager
import logging
from typing import Optional, Literal

logger = logging.getLogger(__name__)

LockResult = Literal["ACQUIRED", "ALREADY_PROCESSED", "LOCKED_BY_OTHER"]


@contextmanager
def acquire_order_lock(db: Session, store_id: int, order_id: str):
    """
    Acquire a database lock for processing an order using SELECT FOR UPDATE.
    Uses NOWAIT to immediately fail if another worker has the lock.

    This prevents the TOCTOU race condition where:
    1. Worker A checks if order is processed (no)
    2. Worker B checks if order is processed (no)
    3. Both workers process the same order

    With this lock:
    1. Worker A acquires lock and checks (no) - proceeds
    2. Worker B tries to acquire lock - fails immediately
    3. Worker A finishes and releases lock

    Args:
        db: SQLAlchemy database session
        store_id: The Shopify store ID
        order_id: The Shopify order ID (gid format)

    Yields:
        LockResult: One of:
            - "ACQUIRED": Lock acquired, order not yet processed, safe to proceed
            - "ALREADY_PROCESSED": Order already has ProcessedOrder record
            - "LOCKED_BY_OTHER": Another worker is processing this order

    Example:
        with acquire_order_lock(db, store.id, order_id) as lock_result:
            if lock_result == "ACQUIRED":
                # Safe to process the order
                process_order(order)
                mark_as_processed(db, store.id, order_id)
            elif lock_result == "ALREADY_PROCESSED":
                logger.info("Order already processed, skipping")
            elif lock_result == "LOCKED_BY_OTHER":
                logger.info("Order being processed by another worker")
    """
    from models import ProcessedOrder

    try:
        stmt = (
            select(ProcessedOrder)
            .where(
                ProcessedOrder.store_id == store_id,
                ProcessedOrder.order_id == order_id
            )
            .with_for_update(nowait=True)
        )

        existing = db.execute(stmt).scalar_one_or_none()

        if existing:
            yield "ALREADY_PROCESSED"
        else:
            yield "ACQUIRED"

    except OperationalError as e:
        error_str = str(e).lower()
        if "lock" in error_str or "nowait" in error_str or "could not obtain" in error_str:
            logger.info(f"Order {order_id} is being processed by another worker")
            yield "LOCKED_BY_OTHER"
        else:
            logger.error(f"Database error while acquiring lock for order {order_id}: {e}")
            raise


def try_mark_order_processed(db: Session, store_id: int, order_id: str) -> bool:
    """
    Attempt to mark an order as processed using INSERT with conflict handling.

    This is the atomic operation that actually prevents duplicate processing.
    Even if the lock check passed, this provides a final safeguard.

    Args:
        db: SQLAlchemy database session
        store_id: The Shopify store ID
        order_id: The Shopify order ID

    Returns:
        True if successfully marked as processed, False if already exists
    """
    from models import ProcessedOrder

    try:
        processed_order = ProcessedOrder(
            store_id=store_id,
            order_id=order_id
        )
        db.add(processed_order)
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        logger.info(f"Order {order_id} already marked as processed (race condition handled)")
        return False


def try_acquire_processing_slot(db: Session, store_id: int, order_id: str) -> bool:
    """
    Try to acquire a processing slot for an order by inserting a ProcessedOrder record
    BEFORE processing begins. This is the most reliable way to prevent duplicate processing.

    The key insight is: instead of check-then-process-then-mark, we mark-then-process.
    If the mark fails (duplicate key), we know another worker got there first.

    Args:
        db: SQLAlchemy database session
        store_id: The Shopify store ID
        order_id: The Shopify order ID

    Returns:
        True if slot acquired (safe to process), False if another worker got it first
    """
    from models import ProcessedOrder

    try:
        processed_order = ProcessedOrder(
            store_id=store_id,
            order_id=order_id
        )
        db.add(processed_order)
        db.flush()
        return True
    except IntegrityError:
        db.rollback()
        logger.debug(f"Order {order_id} already being processed by another worker")
        return False


def release_processing_slot_on_failure(db: Session, store_id: int, order_id: str) -> bool:
    """
    Remove the ProcessedOrder record if processing failed and we want to allow retry.

    This should only be used for transient failures where we want the order
    to be processed again on the next sync.

    Args:
        db: SQLAlchemy database session
        store_id: The Shopify store ID
        order_id: The Shopify order ID

    Returns:
        True if record was removed, False if not found
    """
    from models import ProcessedOrder

    try:
        result = db.query(ProcessedOrder).filter(
            ProcessedOrder.store_id == store_id,
            ProcessedOrder.order_id == order_id
        ).delete()
        db.commit()
        return result > 0
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to release processing slot for order {order_id}: {e}")
        return False
