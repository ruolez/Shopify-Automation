from sqlalchemy import create_engine, pool, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
import os
import sys
import logging

logger = logging.getLogger(__name__)

# PostgreSQL database configuration
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Please set DATABASE_URL in your .env file or environment.", file=sys.stderr)
    print("Example format: postgresql://username:password@host:port/database", file=sys.stderr)
    print("", file=sys.stderr)
    print("For Docker Compose: DATABASE_URL=postgresql://shopify_user:yourpassword@postgres:5432/shopify_db", file=sys.stderr)
    print("For local development: DATABASE_URL=postgresql://shopify_user:yourpassword@localhost:5432/shopify_db", file=sys.stderr)
    sys.exit(1)

# PostgreSQL engine configuration
engine = create_engine(
    DATABASE_URL,
    poolclass=pool.QueuePool,
    pool_size=int(os.getenv("DB_POOL_SIZE", "20")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "40")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "3600")),
    echo=os.getenv("DB_ECHO", "false").lower() == "true",
    connect_args={
        "connect_timeout": 10,
        "options": "-c statement_timeout=30000"  # 30 second statement timeout
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """FastAPI dependency that yields a database session.

    This is a generator function for use with FastAPI's Depends().
    The session is automatically closed when the request completes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session():
    """Database session context manager that ensures proper cleanup.

    Use this for Celery tasks and other non-FastAPI code that needs
    database access. Automatically handles commit on success,
    rollback on exception, and always closes the session.

    Usage:
        with get_db_session() as db:
            # database operations here
            db.query(Model).filter(...).all()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Connection pool monitoring events
@event.listens_for(engine, "checkout")
def log_checkout(dbapi_connection, connection_record, connection_proxy):
    """Log when a connection is checked out from the pool."""
    logger.debug("DB connection checked out from pool")


@event.listens_for(engine, "checkin")
def log_checkin(dbapi_connection, connection_record):
    """Log when a connection is returned to the pool."""
    logger.debug("DB connection returned to pool")


@event.listens_for(engine, "connect")
def log_connect(dbapi_connection, connection_record):
    """Log when a new connection is created."""
    logger.debug("New DB connection created")


@event.listens_for(engine, "close")
def log_close(dbapi_connection, connection_record):
    """Log when a connection is closed."""
    logger.debug("DB connection closed")


def create_tables():
    Base.metadata.create_all(bind=engine)