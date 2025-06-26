import pytest
import asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base, get_db
from models import User
from auth import create_access_token, get_password_hash

# Test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
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
    assert response.status_code == 201
    
    # Login to get token
    login_data = {"username": test_user["email"], "password": test_user["password"]}
    response = client.post("/auth/login", data=login_data)
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
                "parameters": {"tags": "high-value"}
            }
        ],
        "priority": 1,
        "is_active": True
    }