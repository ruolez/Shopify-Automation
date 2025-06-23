import pytest
from fastapi.testclient import TestClient

def test_register_user(client, test_user):
    """Test user registration"""
    response = client.post("/auth/register", json=test_user)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == test_user["email"]
    assert data["full_name"] == test_user["full_name"]
    assert "id" in data

def test_register_duplicate_email(client, test_user):
    """Test registration with duplicate email"""
    # Register first user
    client.post("/auth/register", json=test_user)
    
    # Try to register again with same email
    response = client.post("/auth/register", json=test_user)
    assert response.status_code == 400
    assert "Email already registered" in response.json()["detail"]

def test_login_success(client, test_user):
    """Test successful login"""
    # Register user first
    client.post("/auth/register", json=test_user)
    
    # Login
    login_data = {"username": test_user["email"], "password": test_user["password"]}
    response = client.post("/auth/login", data=login_data)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_login_invalid_credentials(client, test_user):
    """Test login with invalid credentials"""
    # Register user first
    client.post("/auth/register", json=test_user)
    
    # Try login with wrong password
    login_data = {"username": test_user["email"], "password": "wrongpassword"}
    response = client.post("/auth/login", data=login_data)
    assert response.status_code == 401
    assert "Invalid credentials" in response.json()["detail"]

def test_login_nonexistent_user(client):
    """Test login with non-existent user"""
    login_data = {"username": "nonexistent@example.com", "password": "password"}
    response = client.post("/auth/login", data=login_data)
    assert response.status_code == 401

def test_get_current_user(client, auth_headers):
    """Test getting current user info"""
    response = client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "email" in data
    assert "full_name" in data

def test_unauthorized_access(client):
    """Test accessing protected endpoint without token"""
    response = client.get("/auth/me")
    assert response.status_code == 401