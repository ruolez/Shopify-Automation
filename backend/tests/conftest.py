import pytest
import asyncio
import os

# Set test secret keys before importing auth modules
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ADMIN_SECRET_KEY", "test-admin-secret-key-for-testing-only-not-for-production")
# Set test encryption key (valid Fernet key for testing only - DO NOT USE IN PRODUCTION)
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGtleWZvcnRlc3RpbmdwdXJwb3NlczEyMzQ1Ng==")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base, get_db
from models import User
from auth import create_access_token, get_password_hash

# Test database
SQLALCHEMY_DATABASE_URL = "postgresql://test_user:test_pass@localhost:5432/test_db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def test_user():
    return {
        "email": "test@example.com",
        "password": "testpassword123",
        "full_name": "Test User"
    }

@pytest.fixture
def auth_headers(client, test_user):
    # Create user
    response = client.post("/auth/register", json=test_user)
    assert response.status_code == 200
    
    # Login to get token
    login_data = {"email": test_user["email"], "password": test_user["password"]}
    response = client.post("/auth/login", json=login_data)
    assert response.status_code == 200
    
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def test_store_data():
    return {
        "name": "Test Store",
        "shop_domain": "test-store.myshopify.com",
        "access_token": "test_token_123"
    }

@pytest.fixture
def test_rule_data():
    return {
        "name": "Test Rule",
        "description": "Test rule description",
        "conditions": {
            "operator": "AND",
            "conditions": [
                {
                    "field": "order_total",
                    "operator": "greater_than",
                    "value": "100"
                }
            ]
        },
        "actions": [
            {
                "type": "add_tags",
                "parameters": {"tags": "high-value"}
            }
        ],
        "priority": 1,
        "is_active": True
    }

@pytest.fixture
def test_rule_data_legacy():
    """Legacy format for testing backward compatibility"""
    return {
        "name": "Legacy Test Rule",
        "description": "Legacy test rule description",
        "conditions": [
            {
                "field": "order_total",
                "operator": "greater_than",
                "value": "100"
            }
        ],
        "actions": [
            {
                "type": "add_tags",
                "parameters": {"tags": "legacy-rule"}
            }
        ],
        "priority": 1,
        "is_active": True
    }

@pytest.fixture
def test_rule_data_or():
    """OR logic rule for testing"""
    return {
        "name": "OR Test Rule",
        "description": "OR logic test rule",
        "conditions": {
            "operator": "OR",
            "conditions": [
                {
                    "field": "order_total",
                    "operator": "greater_than",
                    "value": "100"
                },
                {
                    "field": "shipping_province",
                    "operator": "equals",
                    "value": "CA"
                }
            ]
        },
        "actions": [
            {
                "type": "add_tags",
                "parameters": {"tags": "or-rule"}
            }
        ],
        "priority": 1,
        "is_active": True
    }