"""
Comprehensive tests for fraud detection system functionality.
Tests the FraudAnalysisService and related API endpoints.
"""
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from main import app
from models import FraudAnalysis, ShopifyStore, User
from fraud_service import FraudAnalysisService
from shopify_client import ShopifyClient
from conftest import override_get_db, TestingSessionLocal


class TestFraudDetectionService:
    """Test the FraudAnalysisService core functionality"""
    
    @pytest.fixture
    def db_session(self):
        """Create a test database session"""
        db = TestingSessionLocal()
        yield db
        db.close()
    
    @pytest.fixture
    def test_user_db(self, db_session):
        """Create a test user in the database"""
        user = User(
            email="test@example.com",
            full_name="Test User",
            hashed_password="hashed_password",
            is_active=True
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user
    
    @pytest.fixture
    def test_store_db(self, db_session, test_user_db):
        """Create a test store in the database"""
        store = ShopifyStore(
            user_id=test_user_db.id,
            shop_domain="test-store.myshopify.com",
            shop_name="Test Store",
            access_token="test_token_123",
            is_active=True
        )
        db_session.add(store)
        db_session.commit()
        db_session.refresh(store)
        return store
    
    @pytest.fixture
    def fraud_service(self, db_session, test_store_db, test_user_db):
        """Create a FraudAnalysisService instance"""
        return FraudAnalysisService(db_session, test_store_db, test_user_db)
    
    @pytest.fixture
    def sample_order_data(self):
        """Sample order data for testing"""
        return {
            "order_info": {
                "id": "gid://shopify/Order/12345",
                "name": "PW110472",
                "total_price": "149.99",
                "created_at": "2025-01-14T10:30:00Z",
                "note": "Test order note"
            },
            "customer": {
                "id": "gid://shopify/Customer/67890",
                "displayName": "John Doe",
                "firstName": "John",
                "lastName": "Doe",
                "email": "john.doe@example.com",
                "numberOfOrders": 2,
                "orders": {
                    "edges": [
                        {
                            "node": {
                                "id": "gid://shopify/Order/12345",
                                "name": "PW110472",
                                "createdAt": "2025-01-14T10:30:00Z",
                                "totalPriceSet": {
                                    "shopMoney": {
                                        "amount": "149.99"
                                    }
                                },
                                "fulfillments": []
                            }
                        },
                        {
                            "node": {
                                "id": "gid://shopify/Order/12344",
                                "name": "PW110471",
                                "createdAt": "2025-01-13T10:30:00Z",
                                "totalPriceSet": {
                                    "shopMoney": {
                                        "amount": "89.99"
                                    }
                                },
                                "fulfillments": [
                                    {
                                        "id": "gid://shopify/Fulfillment/1001",
                                        "displayStatus": "DELIVERED",
                                        "deliveredAt": "2025-01-15T14:30:00Z",
                                        "events": {
                                            "edges": [
                                                {
                                                    "node": {
                                                        "status": "DELIVERED",
                                                        "happenedAt": "2025-01-15T14:30:00Z",
                                                        "message": "Package delivered"
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            },
            "billing_address": {
                "first_name": "John",
                "last_name": "Doe",
                "address1": "123 Main St",
                "city": "New York",
                "province": "New York",
                "country": "US",
                "zip": "10001"
            },
            "shipping_address": {
                "first_name": "John",
                "last_name": "Doe",
                "address1": "123 Main St",
                "city": "New York",
                "province": "New York",
                "country": "US",
                "zip": "10001"
            },
            "transactions": [
                {
                    "id": "gid://shopify/Transaction/1",
                    "status": "SUCCESS",
                    "amount": "149.99"
                }
            ],
            "custom_attributes": [
                {
                    "key": "gift_message",
                    "value": "Happy birthday!"
                }
            ],
            "risk": {
                "assessments": [
                    {
                        "riskLevel": "LOW",
                        "facts": []
                    }
                ]
            },
            "fulfillments": []
        }
    
    def test_check_first_time_customer_true(self, fraud_service, sample_order_data):
        """Test first-time customer detection - should be True"""
        # Modify sample data to indicate first-time customer
        sample_order_data["customer"]["numberOfOrders"] = 1
        sample_order_data["customer"]["orders"]["edges"] = [
            sample_order_data["customer"]["orders"]["edges"][0]
        ]
        
        result = fraud_service._check_first_time_customer(sample_order_data)
        assert result == True
    
    def test_check_first_time_customer_false(self, fraud_service, sample_order_data):
        """Test first-time customer detection - should be False"""
        # Sample data already has numberOfOrders = 2
        result = fraud_service._check_first_time_customer(sample_order_data)
        assert result == False
    
    def test_extract_order_total(self, fraud_service, sample_order_data):
        """Test order total extraction"""
        result = fraud_service._extract_order_total(sample_order_data)
        assert result == Decimal("149.99")
    
    def test_extract_order_total_missing(self, fraud_service):
        """Test order total extraction with missing data"""
        empty_data = {"order_info": {}}
        result = fraud_service._extract_order_total(empty_data)
        assert result == Decimal("0.00")
    
    def test_count_transaction_attempts(self, fraud_service, sample_order_data):
        """Test transaction attempts counting"""
        result = fraud_service._count_transaction_attempts(sample_order_data)
        assert result == 1
    
    def test_count_transaction_attempts_multiple(self, fraud_service, sample_order_data):
        """Test transaction attempts counting with multiple attempts"""
        sample_order_data["transactions"] = [
            {"id": "1", "status": "FAILED"},
            {"id": "2", "status": "SUCCESS"}
        ]
        result = fraud_service._count_transaction_attempts(sample_order_data)
        assert result == 2
    
    def test_extract_customer_name(self, fraud_service, sample_order_data):
        """Test customer name extraction"""
        result = fraud_service._extract_customer_name(sample_order_data)
        assert result == "John Doe"
    
    def test_extract_customer_name_from_billing(self, fraud_service, sample_order_data):
        """Test customer name extraction from billing address when customer data missing"""
        sample_order_data["customer"] = {}
        result = fraud_service._extract_customer_name(sample_order_data)
        assert result == "John Doe"
    
    def test_check_duplicate_within_7days_true(self, fraud_service, sample_order_data):
        """Test duplicate order detection within 7 days - should be True"""
        # Add another order within 7 days
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        sample_order_data["customer"]["orders"]["edges"].append({
            "node": {
                "id": "gid://shopify/Order/12346",
                "name": "PW110473",
                "createdAt": yesterday.isoformat()
            }
        })
        
        result = fraud_service._check_duplicate_within_7days(sample_order_data)
        assert result == True
    
    def test_check_duplicate_within_7days_false(self, fraud_service, sample_order_data):
        """Test duplicate order detection within 7 days - should be False"""
        # All orders in sample data are outside 7 days or are the current order
        result = fraud_service._check_duplicate_within_7days(sample_order_data)
        assert result == False
    
    def test_extract_fraud_risk_level(self, fraud_service, sample_order_data):
        """Test fraud risk level extraction"""
        result = fraud_service._extract_fraud_risk_level(sample_order_data)
        assert result == "LOW"
    
    def test_extract_fraud_risk_level_high(self, fraud_service, sample_order_data):
        """Test fraud risk level extraction - HIGH risk"""
        sample_order_data["risk"]["assessments"][0]["riskLevel"] = "HIGH"
        result = fraud_service._extract_fraud_risk_level(sample_order_data)
        assert result == "HIGH"
    
    def test_extract_fraud_risk_level_missing(self, fraud_service, sample_order_data):
        """Test fraud risk level extraction with missing data"""
        sample_order_data["risk"] = {}
        result = fraud_service._extract_fraud_risk_level(sample_order_data)
        assert result == None
    
    def test_check_same_billing_shipping_true(self, fraud_service, sample_order_data):
        """Test billing/shipping address match - should be True"""
        result = fraud_service._check_same_billing_shipping(sample_order_data)
        assert result == True
    
    def test_check_same_billing_shipping_false(self, fraud_service, sample_order_data):
        """Test billing/shipping address match - should be False"""
        sample_order_data["shipping_address"]["address1"] = "456 Oak Ave"
        result = fraud_service._check_same_billing_shipping(sample_order_data)
        assert result == False
    
    def test_check_billing_address_outside_us_false(self, fraud_service, sample_order_data):
        """Test billing address outside US - should be False (US address)"""
        result = fraud_service._check_billing_address_outside_us(sample_order_data)
        assert result == False
    
    def test_check_billing_address_outside_us_true(self, fraud_service, sample_order_data):
        """Test billing address outside US - should be True (non-US address)"""
        sample_order_data["billing_address"]["country"] = "CA"
        result = fraud_service._check_billing_address_outside_us(sample_order_data)
        assert result == True
    
    def test_extract_shipping_state_uppercase(self, fraud_service, sample_order_data):
        """Test shipping state extraction - should return uppercase"""
        sample_order_data["shipping_address"]["province"] = "California"
        result = fraud_service._extract_shipping_state(sample_order_data)
        assert result == "CALIFORNIA"
    
    def test_extract_shipping_state_none(self, fraud_service, sample_order_data):
        """Test shipping state extraction - should return None when no state"""
        sample_order_data["shipping_address"]["province"] = ""
        result = fraud_service._extract_shipping_state(sample_order_data)
        assert result is None
    
    def test_extract_additional_details(self, fraud_service, sample_order_data):
        """Test additional details extraction"""
        result = fraud_service._extract_additional_details(sample_order_data)
        assert "gift_message Happy birthday!" in result
    
    def test_extract_delivery_tracking_status_unfulfilled(self, fraud_service, sample_order_data):
        """Test delivery tracking status - unfulfilled"""
        result = fraud_service._extract_delivery_tracking_status(sample_order_data)
        assert result == "Unfulfilled"
    
    def test_extract_delivery_tracking_status_delivered(self, fraud_service, sample_order_data):
        """Test delivery tracking status - delivered"""
        sample_order_data["fulfillments"] = [
            {
                "id": "gid://shopify/Fulfillment/1001",
                "displayStatus": "DELIVERED",
                "deliveredAt": "2025-01-15T14:30:00Z",
                "events": {
                    "edges": [
                        {
                            "node": {
                                "status": "DELIVERED",
                                "happenedAt": "2025-01-15T14:30:00Z",
                                "message": "Package delivered"
                            }
                        }
                    ]
                }
            }
        ]
        result = fraud_service._extract_delivery_tracking_status(sample_order_data)
        assert "Delivered on" in result
    
    def test_get_previous_order_data(self, fraud_service, sample_order_data):
        """Test previous order data extraction"""
        delivery_status, order_total = fraud_service._get_previous_order_data(sample_order_data)
        assert delivery_status == "Delivered on January 15th 2025"
        assert order_total == Decimal("89.99")
    
    def test_get_previous_order_data_no_previous(self, fraud_service, sample_order_data):
        """Test previous order data extraction with no previous orders"""
        # Remove previous order, keep only current
        sample_order_data["customer"]["orders"]["edges"] = [
            sample_order_data["customer"]["orders"]["edges"][0]
        ]
        delivery_status, order_total = fraud_service._get_previous_order_data(sample_order_data)
        assert delivery_status == None
        assert order_total == None
    
    def test_analyze_order_fraud_success(self, fraud_service, sample_order_data):
        """Test complete fraud analysis - should succeed"""
        result = fraud_service.analyze_order_fraud(sample_order_data)
        
        assert result is not None
        assert result.order_name == "PW110472"
        assert result.shopify_order_id == "12345"
        assert result.is_first_time_customer == False
        assert result.order_total == Decimal("149.99")
        assert result.transaction_attempts_count == 1
        assert result.customer_name == "John Doe"
        assert result.duplicate_within_7days == False
        assert result.shopify_fraud_risk_level == "LOW"
        assert result.billing_address_outside_us == False
        assert result.same_billing_shipping == True
        assert result.shipping_state == "NEW YORK"  # New York uppercased
        assert result.current_order_delivery_status == "Unfulfilled"
        assert result.previous_order_delivery_status == "Delivered on January 15th 2025"
        assert result.previous_order_total == Decimal("89.99")
    
    def test_analyze_order_fraud_missing_order_id(self, fraud_service, sample_order_data):
        """Test fraud analysis with missing order ID - should fail gracefully"""
        sample_order_data["order_info"]["id"] = ""
        result = fraud_service.analyze_order_fraud(sample_order_data)
        assert result is None
    
    def test_analyze_order_fraud_missing_order_name(self, fraud_service, sample_order_data):
        """Test fraud analysis with missing order name - should fail gracefully"""
        sample_order_data["order_info"]["name"] = ""
        result = fraud_service.analyze_order_fraud(sample_order_data)
        assert result is None


class TestFraudDetectionAPI:
    """Test the fraud detection API endpoints"""
    
    def test_analyze_order_fraud_endpoint_success(self, client, auth_headers):
        """Test fraud analysis API endpoint - success case"""
        # Create a store first
        store_data = {
            "name": "Test Store",
            "shop_domain": "test-store.myshopify.com",
            "access_token": "test_token_123"
        }
        store_response = client.post("/stores", json=store_data, headers=auth_headers)
        assert store_response.status_code == 200
        store_id = store_response.json()["id"]
        
        # Mock the Shopify client
        with patch('main.ShopifyClient') as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            
            # Mock the get_order_fraud_data method
            mock_client.get_order_fraud_data = AsyncMock(return_value={
                "order_info": {
                    "id": "gid://shopify/Order/12345",
                    "name": "PW110472",
                    "total_price": "149.99",
                    "created_at": "2025-01-14T10:30:00Z"
                },
                "customer": {
                    "displayName": "John Doe",
                    "numberOfOrders": 1,
                    "orders": {"edges": []}
                },
                "billing_address": {
                    "country": "US",
                    "province": "Texas"
                },
                "shipping_address": {
                    "country": "US",
                    "province": "Texas"
                },
                "transactions": [{"id": "1", "status": "SUCCESS"}],
                "custom_attributes": [],
                "risk": {"assessments": [{"riskLevel": "LOW"}]},
                "fulfillments": []
            })
            
            # Test the API endpoint
            response = client.post(
                f"/fraud-detection/analyze/{store_id}?order_name=PW110472",
                headers=auth_headers
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "message" in data
            assert "analysis_id" in data
            assert data["message"] == "Fraud analysis completed successfully"
    
    def test_analyze_order_fraud_endpoint_order_not_found(self, client, auth_headers):
        """Test fraud analysis API endpoint - order not found"""
        # Create a store first
        store_data = {
            "name": "Test Store",
            "shop_domain": "test-store.myshopify.com",
            "access_token": "test_token_123"
        }
        store_response = client.post("/stores", json=store_data, headers=auth_headers)
        assert store_response.status_code == 200
        store_id = store_response.json()["id"]
        
        # Mock the Shopify client to return None (order not found)
        with patch('main.ShopifyClient') as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.get_order_fraud_data = AsyncMock(return_value=None)
            
            # Test the API endpoint
            response = client.post(
                f"/fraud-detection/analyze/{store_id}?order_name=NONEXISTENT",
                headers=auth_headers
            )
            
            assert response.status_code == 404
            data = response.json()
            assert data["detail"] == "Order not found in Shopify"
    
    def test_analyze_order_fraud_endpoint_invalid_store(self, client, auth_headers):
        """Test fraud analysis API endpoint - invalid store ID"""
        response = client.post(
            "/fraud-detection/analyze/9999?order_name=PW110472",
            headers=auth_headers
        )
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Store not found"
    
    def test_get_fraud_analyses_endpoint(self, client, auth_headers):
        """Test get fraud analyses endpoint"""
        response = client.get("/fraud-detection/analyses", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "analyses" in data
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert isinstance(data["analyses"], list)
    
    def test_get_fraud_analysis_details_endpoint_not_found(self, client, auth_headers):
        """Test get fraud analysis details endpoint - not found"""
        response = client.get("/fraud-detection/analysis/9999", headers=auth_headers)
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Analysis not found"
    
    def test_get_fraud_detection_stats_endpoint(self, client, auth_headers):
        """Test get fraud detection stats endpoint"""
        response = client.get("/fraud-detection/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_analyses" in data
        assert "period_days" in data
        assert "stats" in data
        assert "risk_level_distribution" in data
        assert "recent_analyses" in data
        
        # Check stats structure
        stats = data["stats"]
        assert "first_time_customers" in stats
        assert "multiple_transaction_attempts" in stats
        assert "duplicate_orders" in stats
        assert "high_fraud_risk" in stats


class TestFraudDetectionEdgeCases:
    """Test edge cases and error conditions"""
    
    def test_fraud_analysis_with_no_customer_data(self, client, auth_headers):
        """Test fraud analysis with guest checkout (no customer data)"""
        # Create a store first
        store_data = {
            "name": "Test Store",
            "shop_domain": "test-store.myshopify.com",
            "access_token": "test_token_123"
        }
        store_response = client.post("/stores", json=store_data, headers=auth_headers)
        assert store_response.status_code == 200
        store_id = store_response.json()["id"]
        
        # Mock order data with no customer
        with patch('main.ShopifyClient') as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.get_order_fraud_data = AsyncMock(return_value={
                "order_info": {
                    "id": "gid://shopify/Order/12345",
                    "name": "PW110472",
                    "total_price": "149.99",
                    "created_at": "2025-01-14T10:30:00Z"
                },
                "customer": None,  # Guest checkout
                "billing_address": {"country": "US", "province": "Texas"},
                "shipping_address": {"country": "US", "province": "Texas"},
                "transactions": [{"id": "1", "status": "SUCCESS"}],
                "custom_attributes": [],
                "risk": {"assessments": [{"riskLevel": "LOW"}]},
                "fulfillments": []
            })
            
            response = client.post(
                f"/fraud-detection/analyze/{store_id}?order_name=PW110472",
                headers=auth_headers
            )
            
            # Should still succeed, but with default values for customer-related fields
            assert response.status_code == 200
    
    def test_fraud_analysis_with_malformed_data(self, client, auth_headers):
        """Test fraud analysis with malformed Shopify data"""
        # Create a store first
        store_data = {
            "name": "Test Store",
            "shop_domain": "test-store.myshopify.com",
            "access_token": "test_token_123"
        }
        store_response = client.post("/stores", json=store_data, headers=auth_headers)
        assert store_response.status_code == 200
        store_id = store_response.json()["id"]
        
        # Mock malformed order data
        with patch('main.ShopifyClient') as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.get_order_fraud_data = AsyncMock(return_value={
                "order_info": {
                    "id": "gid://shopify/Order/12345",
                    "name": "PW110472",
                    "total_price": "invalid_price",  # Invalid price
                    "created_at": "invalid_date"  # Invalid date
                },
                "customer": "invalid_customer_data",  # Should be dict, not string
                "billing_address": None,
                "shipping_address": None,
                "transactions": "invalid_transactions",  # Should be list
                "custom_attributes": None,
                "risk": None,
                "fulfillments": None
            })
            
            response = client.post(
                f"/fraud-detection/analyze/{store_id}?order_name=PW110472",
                headers=auth_headers
            )
            
            # Should handle malformed data gracefully
            assert response.status_code == 200
    
    def test_fraud_analysis_database_error(self, client, auth_headers):
        """Test fraud analysis with database error"""
        # Create a store first
        store_data = {
            "name": "Test Store",
            "shop_domain": "test-store.myshopify.com",
            "access_token": "test_token_123"
        }
        store_response = client.post("/stores", json=store_data, headers=auth_headers)
        assert store_response.status_code == 200
        store_id = store_response.json()["id"]
        
        # Mock Shopify client and database error
        with patch('main.ShopifyClient') as mock_client_class, \
             patch('main.FraudAnalysisService') as mock_service_class:
            
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.get_order_fraud_data = AsyncMock(return_value={"order_info": {"id": "123", "name": "TEST"}})
            
            # Mock service to raise database error
            mock_service = Mock()
            mock_service_class.return_value = mock_service
            mock_service.analyze_order_fraud.return_value = None  # Simulate failure
            
            response = client.post(
                f"/fraud-detection/analyze/{store_id}?order_name=PW110472",
                headers=auth_headers
            )
            
            assert response.status_code == 500
            data = response.json()
            assert data["detail"] == "Failed to analyze order for fraud"