"""
Security tests for authentication, authorization, and other security concerns.
Tests the critical security vulnerabilities identified in the analysis.
"""
import pytest
import jwt
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from main import app
from auth import create_access_token, verify_token, get_password_hash, verify_password, ACCESS_TOKEN_EXPIRE_MINUTES
from admin_auth import create_admin_access_token, verify_admin_token, ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES
from models import User, AdminUser
from conftest import TestingSessionLocal


class TestAuthenticationSecurity:
    """Test authentication security vulnerabilities"""
    
    def test_jwt_token_expiration_time_user(self):
        """Test that user JWT tokens have reasonable expiration time"""
        # Check the configured expiration time
        assert ACCESS_TOKEN_EXPIRE_MINUTES is not None
        
        # Current setting is 30 days (43200 minutes) - this is excessive
        if ACCESS_TOKEN_EXPIRE_MINUTES > 24 * 60:  # More than 24 hours
            pytest.fail(f"User token expiration is too long: {ACCESS_TOKEN_EXPIRE_MINUTES} minutes ({ACCESS_TOKEN_EXPIRE_MINUTES / (60 * 24)} days)")
    
    def test_jwt_token_expiration_time_admin(self):
        """Test that admin JWT tokens have reasonable expiration time"""
        # Check the configured expiration time
        assert ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES is not None
        
        # Admin tokens should be shorter than user tokens
        if ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES > 8 * 60:  # More than 8 hours
            pytest.fail(f"Admin token expiration is too long: {ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES} minutes ({ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES / 60} hours)")
    
    def test_jwt_token_structure_and_validation(self):
        """Test JWT token structure and validation"""
        user_data = {"sub": "test@example.com", "user_id": 1}
        
        # Create token
        token = create_access_token(user_data)
        assert token is not None
        
        # Verify token structure
        try:
            # Decode without verification to check structure
            decoded = jwt.decode(token, options={"verify_signature": False})
            assert "sub" in decoded
            assert "user_id" in decoded
            assert "exp" in decoded
            assert "iat" in decoded
        except Exception as e:
            pytest.fail(f"JWT token structure is invalid: {e}")
    
    def test_jwt_token_verification_with_wrong_secret(self):
        """Test JWT token verification fails with wrong secret"""
        user_data = {"sub": "test@example.com", "user_id": 1}
        token = create_access_token(user_data)
        
        # Try to verify with wrong secret
        with patch('auth.SECRET_KEY', 'wrong-secret-key'):
            try:
                verify_token(token)
                pytest.fail("Token verification should fail with wrong secret")
            except Exception:
                # Expected to fail
                pass
    
    def test_jwt_token_verification_expired(self):
        """Test JWT token verification fails with expired token"""
        user_data = {"sub": "test@example.com", "user_id": 1}
        
        # Create token with very short expiration
        with patch('auth.ACCESS_TOKEN_EXPIRE_MINUTES', 0.01):  # 0.6 seconds
            token = create_access_token(user_data)
            
            # Wait for token to expire
            time.sleep(1)
            
            # Try to verify expired token
            try:
                verify_token(token)
                pytest.fail("Token verification should fail with expired token")
            except Exception:
                # Expected to fail
                pass
    
    def test_password_hashing_security(self):
        """Test password hashing is using secure methods"""
        password = "test_password_123"
        
        # Hash password
        hashed = get_password_hash(password)
        
        # Verify hash is not the same as password
        assert hashed != password
        
        # Verify hash is using bcrypt (should start with $2b$)
        assert hashed.startswith('$2b$')
        
        # Verify password can be verified
        assert verify_password(password, hashed) == True
        
        # Verify wrong password fails
        assert verify_password("wrong_password", hashed) == False
    
    def test_password_strength_requirements(self, client):
        """Test password strength requirements"""
        # Test weak passwords
        weak_passwords = [
            "123",      # Too short
            "password", # Too simple
            "12345678", # All numbers
            "abcdefgh", # All letters
        ]
        
        for weak_password in weak_passwords:
            response = client.post("/auth/register", json={
                "email": "test@example.com",
                "password": weak_password,
                "full_name": "Test User"
            })
            
            # Should reject weak passwords
            if response.status_code == 200:
                pytest.fail(f"Weak password '{weak_password}' was accepted")
    
    def test_admin_default_credentials_vulnerability(self, client):
        """Test for default admin credentials vulnerability"""
        # Try to login with default credentials
        response = client.post("/admin/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        
        # This should fail in production
        if response.status_code == 200:
            pytest.fail("CRITICAL SECURITY VULNERABILITY: Default admin credentials (admin/admin) are still active!")
    
    def test_cors_configuration(self, client):
        """Test CORS configuration"""
        # Test preflight OPTIONS request
        response = client.options("/", headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type"
        })
        
        # Check CORS headers
        headers = response.headers
        
        # Should have CORS headers
        assert "access-control-allow-origin" in headers
        
        # Should not allow all origins in production
        origin = headers.get("access-control-allow-origin")
        if origin == "*":
            pytest.fail("CORS allows all origins (*) - this is insecure for production")
    
    def test_sql_injection_protection(self, client, auth_headers):
        """Test SQL injection protection"""
        # Test various SQL injection attempts
        sql_injection_payloads = [
            "'; DROP TABLE users; --",
            "1 OR 1=1",
            "' UNION SELECT * FROM users --",
            "'; INSERT INTO users VALUES ('hack', 'hack'); --"
        ]
        
        for payload in sql_injection_payloads:
            # Test in search parameters
            response = client.get(f"/order-logs?search={payload}", headers=auth_headers)
            
            # Should not cause server error (500) or return sensitive data
            assert response.status_code != 500, f"SQL injection payload caused server error: {payload}"
    
    def test_xss_protection(self, client, auth_headers):
        """Test XSS protection"""
        # Test XSS payloads
        xss_payloads = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>",
            "';alert('xss');//"
        ]
        
        for payload in xss_payloads:
            # Test in store name
            response = client.post("/stores", json={
                "name": payload,
                "shop_domain": "test.myshopify.com",
                "access_token": "test_token"
            }, headers=auth_headers)
            
            # Should not execute or return unescaped payload
            if response.status_code == 200:
                data = response.json()
                # Check if payload is returned unescaped
                if payload in str(data):
                    pytest.fail(f"XSS payload was not properly escaped: {payload}")
    
    def test_authentication_bypass_attempts(self, client):
        """Test authentication bypass attempts"""
        # Test endpoints that should require authentication
        protected_endpoints = [
            "/stores",
            "/rules",
            "/order-logs",
            "/settings",
            "/fraud-detection/stats"
        ]
        
        for endpoint in protected_endpoints:
            # Try without token
            response = client.get(endpoint)
            assert response.status_code == 401, f"Endpoint {endpoint} should require authentication"
            
            # Try with invalid token
            response = client.get(endpoint, headers={"Authorization": "Bearer invalid_token"})
            assert response.status_code == 401, f"Endpoint {endpoint} should reject invalid token"
    
    def test_admin_endpoint_access_control(self, client):
        """Test admin endpoint access control"""
        # Test admin endpoints that should require admin authentication
        admin_endpoints = [
            "/admin/stats",
            "/admin/users",
            "/admin/stores",
            "/admin/rules",
            "/admin/order-logs"
        ]
        
        for endpoint in admin_endpoints:
            # Try without token
            response = client.get(endpoint)
            assert response.status_code == 401, f"Admin endpoint {endpoint} should require authentication"
            
            # Try with regular user token
            user_token = create_access_token({"sub": "user@example.com", "user_id": 1})
            response = client.get(endpoint, headers={"Authorization": f"Bearer {user_token}"})
            assert response.status_code == 401, f"Admin endpoint {endpoint} should reject user token"
    
    def test_rate_limiting_simulation(self, client):
        """Test rate limiting behavior simulation"""
        # Test multiple rapid requests to auth endpoints
        login_data = {
            "email": "test@example.com",
            "password": "wrong_password"
        }
        
        response_codes = []
        for i in range(10):
            response = client.post("/auth/login", json=login_data)
            response_codes.append(response.status_code)
        
        # Should have some failed logins (401) but not necessarily rate limited
        # This test documents the current behavior
        assert 401 in response_codes, "Failed login attempts should return 401"
    
    def test_sensitive_data_exposure(self, client, auth_headers):
        """Test for sensitive data exposure"""
        # Create a user and store
        store_response = client.post("/stores", json={
            "name": "Test Store",
            "shop_domain": "test.myshopify.com",
            "access_token": "secret_token_123"
        }, headers=auth_headers)
        
        assert store_response.status_code == 200
        
        # Get stores list
        stores_response = client.get("/stores", headers=auth_headers)
        assert stores_response.status_code == 200
        
        stores_data = stores_response.json()
        
        # Check if sensitive data is exposed
        for store in stores_data:
            if "access_token" in store:
                # Access token should be hidden or masked
                if store["access_token"] == "secret_token_123":
                    pytest.fail("Sensitive access token is exposed in API response")
    
    def test_user_data_isolation(self, client):
        """Test user data isolation"""
        # Create two users
        user1_data = {
            "email": "user1@example.com",
            "password": "password123",
            "full_name": "User One"
        }
        
        user2_data = {
            "email": "user2@example.com",
            "password": "password123",
            "full_name": "User Two"
        }
        
        # Register both users
        client.post("/auth/register", json=user1_data)
        client.post("/auth/register", json=user2_data)
        
        # Login as user1
        login1_response = client.post("/auth/login", json={
            "email": user1_data["email"],
            "password": user1_data["password"]
        })
        assert login1_response.status_code == 200
        user1_token = login1_response.json()["access_token"]
        
        # Login as user2
        login2_response = client.post("/auth/login", json={
            "email": user2_data["email"],
            "password": user2_data["password"]
        })
        assert login2_response.status_code == 200
        user2_token = login2_response.json()["access_token"]
        
        # Create store as user1
        store_response = client.post("/stores", json={
            "name": "User1 Store",
            "shop_domain": "user1.myshopify.com",
            "access_token": "user1_token"
        }, headers={"Authorization": f"Bearer {user1_token}"})
        assert store_response.status_code == 200
        
        # Try to access user1's stores as user2
        stores_response = client.get("/stores", headers={"Authorization": f"Bearer {user2_token}"})
        assert stores_response.status_code == 200
        
        user2_stores = stores_response.json()
        
        # User2 should not see user1's stores
        for store in user2_stores:
            if store["name"] == "User1 Store":
                pytest.fail("User data isolation failed: User2 can see User1's stores")


class TestSecurityHeaders:
    """Test security headers and configurations"""
    
    def test_security_headers_presence(self, client):
        """Test presence of security headers"""
        response = client.get("/")
        headers = response.headers
        
        # Check for security headers
        expected_headers = [
            "x-content-type-options",
            "x-frame-options",
            "x-xss-protection"
        ]
        
        for header in expected_headers:
            if header not in headers:
                pytest.fail(f"Missing security header: {header}")
    
    def test_content_type_validation(self, client):
        """Test content type validation"""
        # Test with invalid content type
        response = client.post("/auth/login", 
                              data="invalid_data",
                              headers={"Content-Type": "text/plain"})
        
        # Should reject invalid content type
        assert response.status_code == 422, "Should reject invalid content type"
    
    def test_request_size_limits(self, client):
        """Test request size limits"""
        # Test with very large request
        large_data = {
            "email": "test@example.com",
            "password": "password123",
            "full_name": "x" * 10000,  # Very long name
            "large_field": "x" * 100000  # Very large field
        }
        
        response = client.post("/auth/register", json=large_data)
        
        # Should have some limit or validation
        if response.status_code == 200:
            pytest.fail("Very large request was accepted without validation")


class TestDataValidation:
    """Test data validation and sanitization"""
    
    def test_email_validation(self, client):
        """Test email validation"""
        invalid_emails = [
            "invalid_email",
            "@example.com",
            "user@",
            "user@.com",
            "user@example.",
            ""
        ]
        
        for email in invalid_emails:
            response = client.post("/auth/register", json={
                "email": email,
                "password": "password123",
                "full_name": "Test User"
            })
            
            # Should reject invalid emails
            if response.status_code == 200:
                pytest.fail(f"Invalid email '{email}' was accepted")
    
    def test_shopify_domain_validation(self, client, auth_headers):
        """Test Shopify domain validation"""
        invalid_domains = [
            "not-a-shopify-domain.com",
            "example.com",
            "malicious.example.com",
            "javascript:alert('xss')",
            ""
        ]
        
        for domain in invalid_domains:
            response = client.post("/stores", json={
                "name": "Test Store",
                "shop_domain": domain,
                "access_token": "test_token"
            }, headers=auth_headers)
            
            # Should reject invalid domains
            if response.status_code == 200:
                pytest.fail(f"Invalid Shopify domain '{domain}' was accepted")
    
    def test_input_length_validation(self, client, auth_headers):
        """Test input length validation"""
        # Test very long inputs
        long_string = "x" * 1000
        
        response = client.post("/stores", json={
            "name": long_string,
            "shop_domain": "test.myshopify.com",
            "access_token": "test_token"
        }, headers=auth_headers)
        
        # Should have length validation
        if response.status_code == 200:
            data = response.json()
            if len(data.get("name", "")) > 500:
                pytest.fail("Very long input was accepted without length validation")
    
    def test_null_and_empty_value_handling(self, client, auth_headers):
        """Test null and empty value handling"""
        # Test with null values
        response = client.post("/stores", json={
            "name": None,
            "shop_domain": None,
            "access_token": None
        }, headers=auth_headers)
        
        # Should handle null values gracefully
        assert response.status_code in [400, 422], "Should validate null values"
        
        # Test with empty values
        response = client.post("/stores", json={
            "name": "",
            "shop_domain": "",
            "access_token": ""
        }, headers=auth_headers)
        
        # Should handle empty values gracefully
        assert response.status_code in [400, 422], "Should validate empty values"