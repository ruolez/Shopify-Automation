import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from database import get_db, Base
from models import User
from auth import get_password_hash

# Test database
SQLALCHEMY_DATABASE_URL = "postgresql://test_user:test_pass@localhost:5432/test_db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def test_user():
    db = TestingSessionLocal()
    try:
        user = User(
            email="test@example.com",
            full_name="Test User",
            hashed_password=get_password_hash("testpassword123")
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()

def test_health_check(client):
    """Test health endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "api"}

def test_root_endpoint(client):
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert "Shopify Multi-Store Order Management API" in response.json()["message"]

def test_register_user(client):
    """Test user registration"""
    user_data = {
        "email": "newuser@example.com",
        "full_name": "New User",
        "password": "newpassword123"
    }
    response = client.post("/auth/register", json=user_data)
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert "refresh_token" in response.json()
    assert response.json()["token_type"] == "bearer"
    assert "expires_in" in response.json()

def test_register_duplicate_email(client, test_user):
    """Test registration with duplicate email"""
    user_data = {
        "email": test_user.email,
        "full_name": "Duplicate User",
        "password": "password123"
    }
    response = client.post("/auth/register", json=user_data)
    assert response.status_code == 400
    assert "Email already registered" in response.json()["detail"]

def test_login_success(client, test_user):
    """Test successful login"""
    login_data = {
        "email": test_user.email,
        "password": "testpassword123"
    }
    response = client.post("/auth/login", json=login_data)
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert "refresh_token" in response.json()
    assert "expires_in" in response.json()

def test_login_invalid_credentials(client):
    """Test login with invalid credentials"""
    login_data = {
        "email": "invalid@example.com",
        "password": "wrongpassword"
    }
    response = client.post("/auth/login", json=login_data)
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]

def test_get_current_user(client, test_user):
    """Test getting current user info"""
    # Login first
    login_data = {
        "email": test_user.email,
        "password": "testpassword123"
    }
    login_response = client.post("/auth/login", json=login_data)
    token = login_response.json()["access_token"]
    
    # Get user info
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == test_user.email
    assert response.json()["full_name"] == test_user.full_name

def test_unauthorized_access(client):
    """Test accessing protected endpoint without token"""
    response = client.get("/auth/me")
    assert response.status_code == 403  # No auth header


def test_refresh_token(client, test_user):
    """Test refreshing access token"""
    # Login first to get tokens
    login_data = {
        "email": test_user.email,
        "password": "testpassword123"
    }
    login_response = client.post("/auth/login", json=login_data)
    refresh_token = login_response.json()["refresh_token"]

    # Use refresh token to get new tokens
    response = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert "refresh_token" in response.json()
    assert "expires_in" in response.json()


def test_refresh_token_invalid(client):
    """Test refreshing with invalid token"""
    response = client.post("/auth/refresh", json={"refresh_token": "invalid_token"})
    assert response.status_code == 401


def test_get_stores_empty(client, test_user):
    """Test getting stores for user with no stores"""
    # Login first
    login_data = {
        "email": test_user.email,
        "password": "testpassword123"
    }
    login_response = client.post("/auth/login", json=login_data)
    token = login_response.json()["access_token"]
    
    # Get stores
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/stores", headers=headers)
    assert response.status_code == 200
    assert response.json() == []

def test_get_rules_empty(client, test_user):
    """Test getting rules for user with no rules"""
    # Login first
    login_data = {
        "email": test_user.email,
        "password": "testpassword123"
    }
    login_response = client.post("/auth/login", json=login_data)
    token = login_response.json()["access_token"]
    
    # Get rules
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/rules", headers=headers)
    assert response.status_code == 200
    assert response.json() == []

def test_get_rule_schema(client):
    """Test getting rule schema"""
    response = client.get("/rules/schema")
    assert response.status_code == 200
    data = response.json()
    assert "fields" in data
    assert "operators" in data
    assert "action_types" in data
    assert len(data["fields"]) > 0
    assert len(data["operators"]) > 0
    assert len(data["action_types"]) > 0

def test_dashboard_stats(client, test_user):
    """Test dashboard stats endpoint"""
    # Login first
    login_data = {
        "email": test_user.email,
        "password": "testpassword123"
    }
    login_response = client.post("/auth/login", json=login_data)
    token = login_response.json()["access_token"]
    
    # Get dashboard stats
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/dashboard/stats", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "stores" in data
    assert "rules" in data
    assert "recent_activity" in data
    assert data["stores"]["total"] == 0
    assert data["rules"]["total"] == 0