"""
Tests for SKU exclusion system functionality.
Tests the SKU exclusion feature that affects weight calculations and OOS reporting.
"""
import pytest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from decimal import Decimal

from main import app
from models import ExcludedSKU, User, ShopifyStore
from rule_engine import RuleEngine
from tasks import _record_oos_incident, _record_oos_incident_for_failed_items, _record_oos_incident_for_unavailable_items, _check_inventory_availability
from conftest import TestingSessionLocal


class TestSKUExclusionAPI:
    """Test SKU exclusion API endpoints"""
    
    def test_create_excluded_sku_success(self, client, auth_headers):
        """Test creating excluded SKU successfully"""
        sku_data = {
            "sku_pattern": "TEST",
            "description": "Test SKU pattern",
            "is_active": True
        }
        
        response = client.post("/settings/excluded-skus", json=sku_data, headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert data["sku_pattern"] == "TEST"
        assert data["description"] == "Test SKU pattern"
        assert data["is_active"] == True
        assert "id" in data
        assert "created_at" in data
    
    def test_create_excluded_sku_duplicate(self, client, auth_headers):
        """Test creating duplicate excluded SKU"""
        sku_data = {
            "sku_pattern": "DUPLICATE",
            "description": "First pattern",
            "is_active": True
        }
        
        # Create first SKU
        response1 = client.post("/settings/excluded-skus", json=sku_data, headers=auth_headers)
        assert response1.status_code == 200
        
        # Try to create duplicate
        response2 = client.post("/settings/excluded-skus", json=sku_data, headers=auth_headers)
        assert response2.status_code == 400
        assert "already exists" in response2.json()["detail"]
    
    def test_get_excluded_skus(self, client, auth_headers):
        """Test getting excluded SKUs list"""
        # Create some SKUs first
        sku_data1 = {"sku_pattern": "TEST1", "description": "Test 1", "is_active": True}
        sku_data2 = {"sku_pattern": "TEST2", "description": "Test 2", "is_active": False}
        
        client.post("/settings/excluded-skus", json=sku_data1, headers=auth_headers)
        client.post("/settings/excluded-skus", json=sku_data2, headers=auth_headers)
        
        # Get all SKUs
        response = client.get("/settings/excluded-skus", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert len(data) == 2
        
        # Check data structure
        for sku in data:
            assert "id" in sku
            assert "sku_pattern" in sku
            assert "description" in sku
            assert "is_active" in sku
            assert "created_at" in sku
    
    def test_update_excluded_sku_success(self, client, auth_headers):
        """Test updating excluded SKU successfully"""
        # Create SKU first
        sku_data = {"sku_pattern": "UPDATE_TEST", "description": "Original", "is_active": True}
        create_response = client.post("/settings/excluded-skus", json=sku_data, headers=auth_headers)
        assert create_response.status_code == 200
        sku_id = create_response.json()["id"]
        
        # Update SKU
        update_data = {"description": "Updated description", "is_active": False}
        response = client.put(f"/settings/excluded-skus/{sku_id}", json=update_data, headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert data["description"] == "Updated description"
        assert data["is_active"] == False
        assert data["sku_pattern"] == "UPDATE_TEST"  # Should remain unchanged
    
    def test_update_excluded_sku_not_found(self, client, auth_headers):
        """Test updating non-existent excluded SKU"""
        update_data = {"description": "Updated", "is_active": False}
        response = client.put("/settings/excluded-skus/9999", json=update_data, headers=auth_headers)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    def test_delete_excluded_sku_success(self, client, auth_headers):
        """Test deleting excluded SKU successfully"""
        # Create SKU first
        sku_data = {"sku_pattern": "DELETE_TEST", "description": "To be deleted", "is_active": True}
        create_response = client.post("/settings/excluded-skus", json=sku_data, headers=auth_headers)
        assert create_response.status_code == 200
        sku_id = create_response.json()["id"]
        
        # Delete SKU
        response = client.delete(f"/settings/excluded-skus/{sku_id}", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "deleted successfully" in data["message"]
        
        # Verify it's deleted
        get_response = client.get("/settings/excluded-skus", headers=auth_headers)
        remaining_skus = get_response.json()
        assert not any(sku["id"] == sku_id for sku in remaining_skus)
    
    def test_delete_excluded_sku_not_found(self, client, auth_headers):
        """Test deleting non-existent excluded SKU"""
        response = client.delete("/settings/excluded-skus/9999", headers=auth_headers)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    def test_excluded_sku_user_isolation(self, client):
        """Test that excluded SKUs are isolated per user"""
        # Create two users
        user1_data = {"email": "user1@test.com", "password": "password123", "full_name": "User 1"}
        user2_data = {"email": "user2@test.com", "password": "password123", "full_name": "User 2"}
        
        client.post("/auth/register", json=user1_data)
        client.post("/auth/register", json=user2_data)
        
        # Login as user1
        login1_response = client.post("/auth/login", json={"email": user1_data["email"], "password": user1_data["password"]})
        user1_token = login1_response.json()["access_token"]
        user1_headers = {"Authorization": f"Bearer {user1_token}"}
        
        # Login as user2
        login2_response = client.post("/auth/login", json={"email": user2_data["email"], "password": user2_data["password"]})
        user2_token = login2_response.json()["access_token"]
        user2_headers = {"Authorization": f"Bearer {user2_token}"}
        
        # Create SKU as user1
        sku_data = {"sku_pattern": "USER1_SKU", "description": "User 1 SKU", "is_active": True}
        response = client.post("/settings/excluded-skus", json=sku_data, headers=user1_headers)
        assert response.status_code == 200
        
        # User2 should not see user1's SKU
        response = client.get("/settings/excluded-skus", headers=user2_headers)
        assert response.status_code == 200
        user2_skus = response.json()
        assert len(user2_skus) == 0
        
        # User1 should see their own SKU
        response = client.get("/settings/excluded-skus", headers=user1_headers)
        assert response.status_code == 200
        user1_skus = response.json()
        assert len(user1_skus) == 1
        assert user1_skus[0]["sku_pattern"] == "USER1_SKU"


class TestSKUExclusionInRuleEngine:
    """Test SKU exclusion in rule engine weight calculations"""
    
    def test_weight_calculation_with_excluded_skus(self):
        """Test weight calculation excludes specified SKUs"""
        engine = RuleEngine()
        
        # Mock order with multiple line items
        order_data = {
            "name": "TEST123",
            "currentTotalWeight": 500,  # Total weight including excluded items
            "lineItems": {
                "edges": [
                    {
                        "node": {
                            "title": "Product 1",
                            "quantity": 2,
                            "variant": {
                                "sku": "REGULAR_SKU_001",
                                "inventoryItem": {
                                    "measurement": {
                                        "weight": {
                                            "value": 100,
                                            "unit": "GRAMS"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    {
                        "node": {
                            "title": "Test Product",
                            "quantity": 1,
                            "variant": {
                                "sku": "TEST_SKU_001",  # Should be excluded
                                "inventoryItem": {
                                    "measurement": {
                                        "weight": {
                                            "value": 300,
                                            "unit": "GRAMS"
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        # Test without exclusions
        weight_without_exclusions = engine._get_order_field_value("order_weight", order_data)
        assert weight_without_exclusions == 500  # Should use Shopify's value when no exclusions
        
        # Test with exclusions
        excluded_skus = ["TEST"]
        weight_with_exclusions = engine._get_order_field_value("order_weight", order_data, excluded_skus)
        assert weight_with_exclusions == 200  # 2 * 100g = 200g (excluded 300g item)
    
    def test_weight_calculation_case_insensitive_exclusion(self):
        """Test weight calculation exclusion is case insensitive"""
        engine = RuleEngine()
        
        order_data = {
            "name": "TEST123",
            "currentTotalWeight": 300,
            "lineItems": {
                "edges": [
                    {
                        "node": {
                            "title": "Test Product",
                            "quantity": 1,
                            "variant": {
                                "sku": "test_sku_001",  # lowercase
                                "inventoryItem": {
                                    "measurement": {
                                        "weight": {
                                            "value": 300,
                                            "unit": "GRAMS"
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        # Test with uppercase exclusion pattern
        excluded_skus = ["TEST"]
        weight = engine._get_order_field_value("order_weight", order_data, excluded_skus)
        assert weight == 0  # Should exclude the item
    
    def test_weight_calculation_multiple_exclusion_patterns(self):
        """Test weight calculation with multiple exclusion patterns"""
        engine = RuleEngine()
        
        order_data = {
            "name": "TEST123",
            "currentTotalWeight": 600,
            "lineItems": {
                "edges": [
                    {
                        "node": {
                            "title": "Regular Product",
                            "quantity": 1,
                            "variant": {
                                "sku": "REGULAR_001",
                                "inventoryItem": {
                                    "measurement": {
                                        "weight": {
                                            "value": 100,
                                            "unit": "GRAMS"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    {
                        "node": {
                            "title": "Test Product",
                            "quantity": 1,
                            "variant": {
                                "sku": "TEST_001",
                                "inventoryItem": {
                                    "measurement": {
                                        "weight": {
                                            "value": 200,
                                            "unit": "GRAMS"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    {
                        "node": {
                            "title": "Sample Product",
                            "quantity": 1,
                            "variant": {
                                "sku": "SAMPLE_001",
                                "inventoryItem": {
                                    "measurement": {
                                        "weight": {
                                            "value": 300,
                                            "unit": "GRAMS"
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        # Test with multiple exclusion patterns
        excluded_skus = ["TEST", "SAMPLE"]
        weight = engine._get_order_field_value("order_weight", order_data, excluded_skus)
        assert weight == 100  # Only regular product should be counted
    
    def test_weight_calculation_no_excluded_skus(self):
        """Test weight calculation with empty exclusion list"""
        engine = RuleEngine()
        
        order_data = {
            "name": "TEST123",
            "currentTotalWeight": 300,
            "lineItems": {
                "edges": [
                    {
                        "node": {
                            "title": "Test Product",
                            "quantity": 1,
                            "variant": {
                                "sku": "TEST_001",
                                "inventoryItem": {
                                    "measurement": {
                                        "weight": {
                                            "value": 300,
                                            "unit": "GRAMS"
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        # Test with empty exclusion list
        excluded_skus = []
        weight = engine._get_order_field_value("order_weight", order_data, excluded_skus)
        assert weight == 300  # Should use Shopify's value when no exclusions
        
        # Test with None exclusion list
        weight = engine._get_order_field_value("order_weight", order_data, None)
        assert weight == 300  # Should use Shopify's value when no exclusions


class TestSKUExclusionInOOSReporting:
    """Test SKU exclusion in Out-of-Stock reporting"""
    
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
    
    def test_record_oos_incident_excludes_skus(self, db_session, test_user_db, test_store_db):
        """Test that OOS incident recording excludes specified SKUs"""
        order_data = {
            "id": "gid://shopify/Order/12345",
            "name": "TEST123",
            "lineItems": {
                "edges": [
                    {
                        "node": {
                            "title": "Regular Product",
                            "quantity": 1,
                            "product": {
                                "id": "gid://shopify/Product/1",
                                "vendor": "Test Vendor",
                                "productType": "Regular"
                            },
                            "variant": {
                                "id": "gid://shopify/ProductVariant/1",
                                "title": "Default Title",
                                "sku": "REGULAR_001"
                            }
                        }
                    },
                    {
                        "node": {
                            "title": "Test Product",
                            "quantity": 1,
                            "product": {
                                "id": "gid://shopify/Product/2",
                                "vendor": "Test Vendor",
                                "productType": "Test"
                            },
                            "variant": {
                                "id": "gid://shopify/ProductVariant/2",
                                "title": "Default Title",
                                "sku": "TEST_001"
                            }
                        }
                    }
                ]
            }
        }
        
        # Record OOS incident with exclusions
        excluded_skus = ["TEST"]
        _record_oos_incident(
            db=db_session,
            user_id=test_user_db.id,
            store_id=test_store_db.id,
            order=order_data,
            rule_name="Test Rule",
            attempted_location_id="gid://shopify/Location/1",
            excluded_skus=excluded_skus
        )
        
        # Check that only non-excluded SKU was recorded
        from models import OutOfStockIncident
        incidents = db_session.query(OutOfStockIncident).all()
        assert len(incidents) == 1
        assert incidents[0].sku == "REGULAR_001"
        assert incidents[0].product_title == "Regular Product"
    
    def test_record_oos_incident_for_failed_items_excludes_skus(self, db_session, test_user_db, test_store_db):
        """Test that OOS incident recording for failed items excludes specified SKUs"""
        order_data = {
            "id": "gid://shopify/Order/12345",
            "name": "TEST123",
            "lineItems": {
                "edges": [
                    {
                        "node": {
                            "variant": {
                                "id": "gid://shopify/ProductVariant/1",
                                "title": "Default Title",
                                "sku": "REGULAR_001"
                            }
                        }
                    },
                    {
                        "node": {
                            "variant": {
                                "id": "gid://shopify/ProductVariant/2",
                                "title": "Default Title",
                                "sku": "TEST_001"
                            }
                        }
                    }
                ]
            }
        }
        
        failed_items = [
            {
                "product_title": "Regular Product",
                "product_id": "gid://shopify/Product/1",
                "variant_id": "gid://shopify/ProductVariant/1",
                "sku": "REGULAR_001",
                "failed_quantity": 1
            },
            {
                "product_title": "Test Product",
                "product_id": "gid://shopify/Product/2",
                "variant_id": "gid://shopify/ProductVariant/2",
                "sku": "TEST_001",
                "failed_quantity": 1
            }
        ]
        
        # Record OOS incident for failed items with exclusions
        excluded_skus = ["TEST"]
        _record_oos_incident_for_failed_items(
            db=db_session,
            user_id=test_user_db.id,
            store_id=test_store_db.id,
            order=order_data,
            rule_name="Test Rule",
            attempted_location_id="gid://shopify/Location/1",
            failed_items=failed_items,
            excluded_skus=excluded_skus
        )
        
        # Check that only non-excluded SKU was recorded
        from models import OutOfStockIncident
        incidents = db_session.query(OutOfStockIncident).all()
        assert len(incidents) == 1
        assert incidents[0].sku == "REGULAR_001"
        assert incidents[0].product_title == "Regular Product"
    
    def test_record_oos_incident_for_unavailable_items_excludes_skus(self, db_session, test_user_db, test_store_db):
        """Test that OOS incident recording for unavailable items excludes specified SKUs"""
        order_data = {
            "id": "gid://shopify/Order/12345",
            "name": "TEST123",
            "lineItems": {
                "edges": [
                    {
                        "node": {
                            "title": "Regular Product",
                            "product": {
                                "id": "gid://shopify/Product/1"
                            },
                            "variant": {
                                "id": "gid://shopify/ProductVariant/1",
                                "title": "Default Title"
                            }
                        }
                    },
                    {
                        "node": {
                            "title": "Test Product",
                            "product": {
                                "id": "gid://shopify/Product/2"
                            },
                            "variant": {
                                "id": "gid://shopify/ProductVariant/2",
                                "title": "Default Title"
                            }
                        }
                    }
                ]
            }
        }
        
        unavailable_items = [
            {
                "product_title": "Regular Product",
                "variant_id": "gid://shopify/ProductVariant/1",
                "sku": "REGULAR_001",
                "required_quantity": 1,
                "available_quantity": 0
            },
            {
                "product_title": "Test Product",
                "variant_id": "gid://shopify/ProductVariant/2",
                "sku": "TEST_001",
                "required_quantity": 1,
                "available_quantity": 0
            }
        ]
        
        # Record OOS incident for unavailable items with exclusions
        excluded_skus = ["TEST"]
        _record_oos_incident_for_unavailable_items(
            db=db_session,
            user_id=test_user_db.id,
            store_id=test_store_db.id,
            order=order_data,
            rule_name="Test Rule",
            attempted_location_id="gid://shopify/Location/1",
            unavailable_items=unavailable_items,
            excluded_skus=excluded_skus
        )
        
        # Check that only non-excluded SKU was recorded
        from models import OutOfStockIncident
        incidents = db_session.query(OutOfStockIncident).all()
        assert len(incidents) == 1
        assert incidents[0].sku == "REGULAR_001"
        assert incidents[0].product_title == "Regular Product"
    
    def test_oos_incident_exclusion_missing_sku_data(self, db_session, test_user_db, test_store_db):
        """Test OOS incident exclusion when SKU data is missing"""
        order_data = {
            "id": "gid://shopify/Order/12345",
            "name": "TEST123",
            "lineItems": {
                "edges": [
                    {
                        "node": {
                            "title": "Product with no SKU",
                            "quantity": 1,
                            "product": {
                                "id": "gid://shopify/Product/1",
                                "vendor": "Test Vendor",
                                "productType": "Regular"
                            },
                            "variant": {
                                "id": "gid://shopify/ProductVariant/1",
                                "title": "Default Title",
                                "sku": ""  # Empty SKU
                            }
                        }
                    }
                ]
            }
        }
        
        # Record OOS incident with exclusions
        excluded_skus = ["TEST"]
        _record_oos_incident(
            db=db_session,
            user_id=test_user_db.id,
            store_id=test_store_db.id,
            order=order_data,
            rule_name="Test Rule",
            attempted_location_id="gid://shopify/Location/1",
            excluded_skus=excluded_skus
        )
        
        # Should record incident even with empty SKU (can't exclude what we don't have)
        from models import OutOfStockIncident
        incidents = db_session.query(OutOfStockIncident).all()
        assert len(incidents) == 1
        assert incidents[0].sku == ""
        assert incidents[0].product_title == "Product with no SKU"


class TestSKUExclusionInInventoryCheck:
    """Test SKU exclusion in inventory availability checking"""
    
    @pytest.mark.asyncio
    async def test_inventory_check_excludes_skus(self):
        """Test that inventory check excludes specified SKUs"""
        # Mock Shopify client
        mock_client = Mock()
        mock_client.check_inventory_at_location = Mock(return_value=10)
        
        fulfillment_order = {
            "lineItems": {
                "edges": [
                    {
                        "node": {
                            "variant": {
                                "id": "gid://shopify/ProductVariant/1",
                                "sku": "REGULAR_001",
                                "product": {
                                    "title": "Regular Product"
                                }
                            },
                            "totalQuantity": 2
                        }
                    },
                    {
                        "node": {
                            "variant": {
                                "id": "gid://shopify/ProductVariant/2",
                                "sku": "TEST_001",
                                "product": {
                                    "title": "Test Product"
                                }
                            },
                            "totalQuantity": 1
                        }
                    }
                ]
            }
        }
        
        # Test with exclusions
        excluded_skus = ["TEST"]
        result = await _check_inventory_availability(
            client=mock_client,
            fulfillment_order=fulfillment_order,
            target_location_id="gid://shopify/Location/1",
            order_name="TEST123",
            excluded_skus=excluded_skus
        )
        
        # Should have 2 available items (1 regular + 1 excluded)
        assert result["all_available"] == True
        assert len(result["available_items"]) == 2
        assert len(result["unavailable_items"]) == 0
        
        # Check that excluded SKU was marked as such
        excluded_item = next(item for item in result["available_items"] if item["sku"] == "TEST_001")
        assert excluded_item["available_quantity"] == "excluded_sku"
        assert excluded_item["skipped_from_check"] == True
    
    @pytest.mark.asyncio
    async def test_inventory_check_no_exclusions(self):
        """Test inventory check without exclusions"""
        # Mock Shopify client
        mock_client = Mock()
        mock_client.check_inventory_at_location = Mock(return_value=10)
        
        fulfillment_order = {
            "lineItems": {
                "edges": [
                    {
                        "node": {
                            "variant": {
                                "id": "gid://shopify/ProductVariant/1",
                                "sku": "REGULAR_001",
                                "product": {
                                    "title": "Regular Product"
                                }
                            },
                            "totalQuantity": 2
                        }
                    }
                ]
            }
        }
        
        # Test without exclusions
        result = await _check_inventory_availability(
            client=mock_client,
            fulfillment_order=fulfillment_order,
            target_location_id="gid://shopify/Location/1",
            order_name="TEST123",
            excluded_skus=None
        )
        
        # Should check inventory normally
        assert result["all_available"] == True
        assert len(result["available_items"]) == 1
        assert len(result["unavailable_items"]) == 0
        
        # Verify inventory was actually checked
        mock_client.check_inventory_at_location.assert_called_once_with(
            "gid://shopify/ProductVariant/1",
            "gid://shopify/Location/1"
        )
    
    @pytest.mark.asyncio
    async def test_inventory_check_empty_line_items(self):
        """Test inventory check with empty line items"""
        mock_client = Mock()
        
        fulfillment_order = {
            "lineItems": {
                "edges": []
            }
        }
        
        # Test with empty line items
        result = await _check_inventory_availability(
            client=mock_client,
            fulfillment_order=fulfillment_order,
            target_location_id="gid://shopify/Location/1",
            order_name="TEST123",
            excluded_skus=["TEST"]
        )
        
        # Should return error
        assert result["all_available"] == False
        assert "error" in result
        assert "No line items found" in result["error"]