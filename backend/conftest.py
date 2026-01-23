"""
PostgreSQL Test Configuration
Provides test fixtures and database setup for pytest
"""

import pytest
import os

# Set test secret keys before importing auth modules
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ADMIN_SECRET_KEY", "test-admin-secret-key-for-testing-only-not-for-production")
# Set test encryption key (valid Fernet key for testing only - DO NOT USE IN PRODUCTION)
# This is a valid Fernet key format: 32 bytes URL-safe base64 encoded = 44 chars
# Key value: "testkeyfortestingpurposes123456" (32 chars) base64 encoded
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGtleWZvcnRlc3RpbmdwdXJwb3NlczEyMzQ1Ng==")
import asyncio
from typing import Generator, AsyncGenerator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Import your models and database setup
from database import Base, get_db
from models import *

# Test database configuration
TEST_DATABASE_NAME = "test_shopify_db"
TEST_DATABASE_USER = os.getenv("TEST_DB_USER", "shopify_user")
TEST_DATABASE_PASSWORD = os.getenv("TEST_DB_PASSWORD", "testpass")
TEST_DATABASE_HOST = os.getenv("TEST_DB_HOST", "localhost")
TEST_DATABASE_PORT = os.getenv("TEST_DB_PORT", "5432")

# PostgreSQL for tests
TEST_DATABASE_URL = f"postgresql://{TEST_DATABASE_USER}:{TEST_DATABASE_PASSWORD}@{TEST_DATABASE_HOST}:{TEST_DATABASE_PORT}/{TEST_DATABASE_NAME}"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_database():
    """Create test database for the session."""
    # Create PostgreSQL test database
        conn = psycopg2.connect(
            host=TEST_DATABASE_HOST,
            port=TEST_DATABASE_PORT,
            user=TEST_DATABASE_USER,
            password=TEST_DATABASE_PASSWORD,
            database="postgres"
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Drop test database if exists and create new one
        cursor.execute(f"DROP DATABASE IF EXISTS {TEST_DATABASE_NAME}")
        cursor.execute(f"CREATE DATABASE {TEST_DATABASE_NAME}")
        
        cursor.close()
        conn.close()
        
        # Create engine for test database
        engine = create_engine(
            TEST_DATABASE_URL,
            poolclass=NullPool,  # Disable pooling for tests
            echo=False
        )
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    yield engine
    
    # Cleanup
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    
    # Drop test database
        conn = psycopg2.connect(
            host=TEST_DATABASE_HOST,
            port=TEST_DATABASE_PORT,
            user=TEST_DATABASE_USER,
            password=TEST_DATABASE_PASSWORD,
            database="postgres"
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS {TEST_DATABASE_NAME}")
        cursor.close()
        conn.close()


@pytest.fixture(scope="function")
def db_session(test_database) -> Generator[Session, None, None]:
    """Create a new database session for each test."""
    TestSessionLocal = sessionmaker(
        autocommit=False, 
        autoflush=False, 
        bind=test_database
    )
    
    session = TestSessionLocal()
    
    # Begin a transaction
    if USE_POSTGRESQL:
        session.execute(text("BEGIN"))
    
    try:
        yield session
    finally:
        # Rollback the transaction
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with database session override."""
    from main import app
    from fastapi.testclient import TestClient
    
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as test_client:
        yield test_client
    
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    from models import User
    import bcrypt

    hashed = bcrypt.hashpw("testpassword".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=hashed,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_admin_user(db_session):
    """Create a test admin user."""
    from models import AdminUser
    import bcrypt

    hashed = bcrypt.hashpw("adminpassword".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    admin = AdminUser(
        username="admin",
        email="admin@example.com",
        hashed_password=hashed,
        is_active=True,
        is_superuser=True
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


@pytest.fixture
def test_store(db_session, test_user):
    """Create a test Shopify store."""
    from models import ShopifyStore
    
    store = ShopifyStore(
        user_id=test_user.id,
        store_name="Test Store",
        store_url="test-store.myshopify.com",
        access_token="test_token_123",
        is_active=True
    )
    db_session.add(store)
    db_session.commit()
    db_session.refresh(store)
    return store


@pytest.fixture
def test_processing_rule(db_session, test_user):
    """Create a test processing rule."""
    from models import ProcessingRule
    import json
    
    rule = ProcessingRule(
        user_id=test_user.id,
        name="Test Rule",
        description="Test processing rule",
        conditions=json.dumps({
            "field": "total_price",
            "operator": "greater_than",
            "value": "100"
        }),
        actions=json.dumps({
            "type": "add_tag",
            "value": "high_value"
        }),
        priority=1,
        is_active=True
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)
    return rule


@pytest.fixture
def test_fraud_rule(db_session, test_user):
    """Create a test fraud detection rule."""
    from models import FraudDetectionRule
    import json
    
    rule = FraudDetectionRule(
        user_id=test_user.id,
        name="Test Fraud Rule",
        description="Test fraud detection rule",
        conditions=json.dumps({
            "field": "risk_score",
            "operator": "greater_than",
            "value": "0.8"
        }),
        actions=json.dumps({
            "type": "flag_fraud",
            "notify": True
        }),
        priority=1,
        is_active=True
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)
    return rule


@pytest.fixture
def auth_headers(test_user):
    """Generate authentication headers for test user."""
    from jose import jwt
    from datetime import datetime, timedelta, timezone

    SECRET_KEY = os.getenv("SECRET_KEY", "test-secret-key")
    ALGORITHM = "HS256"

    access_token_expires = timedelta(minutes=30)
    expire = datetime.now(timezone.utc) + access_token_expires
    
    to_encode = {
        "sub": test_user.email,
        "exp": expire
    }
    
    access_token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(autouse=True)
def reset_database(db_session):
    """Reset database state before each test."""
    # Clear all tables in reverse order of dependencies
    if USE_POSTGRESQL:
        db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    
    # Delete all records from tables
    for table in reversed(Base.metadata.sorted_tables):
        db_session.execute(table.delete())
    
    db_session.commit()
    yield
    # Cleanup happens automatically with transaction rollback


# Markers for different test types
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "postgresql: mark test as requiring PostgreSQL"
    )
    config.addinivalue_line(
        "markers", "sqlite: mark test as requiring SQLite"
    )