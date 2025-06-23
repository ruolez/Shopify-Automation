import pytest
from unittest.mock import patch, AsyncMock

def test_get_stores_empty(client, auth_headers):
    """Test getting stores when none exist"""
    response = client.get("/stores", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []

@patch('main.ShopifyClient')
def test_add_store_success(mock_shopify_client, client, auth_headers, test_store_data):
    """Test adding a new store successfully"""
    # Mock successful store connection
    mock_instance = mock_shopify_client.return_value
    mock_instance.test_connection = AsyncMock(return_value=True)
    mock_instance.get_shop_info = AsyncMock(return_value={
        "name": "Test Store",
        "domain": "test-store.myshopify.com"
    })
    
    response = client.post("/stores", json=test_store_data, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == test_store_data["name"]
    assert data["shop_domain"] == test_store_data["shop_domain"]
    assert "id" in data

@patch('main.ShopifyClient')
def test_add_store_invalid_token(mock_shopify_client, client, auth_headers, test_store_data):
    """Test adding store with invalid token"""
    # Mock failed connection
    mock_instance = mock_shopify_client.return_value
    mock_instance.test_connection = AsyncMock(return_value=False)
    
    response = client.post("/stores", json=test_store_data, headers=auth_headers)
    assert response.status_code == 400
    assert "Invalid store credentials" in response.json()["detail"]

@patch('main.ShopifyClient')
def test_get_stores_with_data(mock_shopify_client, client, auth_headers, test_store_data):
    """Test getting stores after adding one"""
    # Mock successful store connection
    mock_instance = mock_shopify_client.return_value
    mock_instance.test_connection = AsyncMock(return_value=True)
    mock_instance.get_shop_info = AsyncMock(return_value={
        "name": "Test Store",
        "domain": "test-store.myshopify.com"
    })
    
    # Add store
    client.post("/stores", json=test_store_data, headers=auth_headers)
    
    # Get stores
    response = client.get("/stores", headers=auth_headers)
    assert response.status_code == 200
    stores = response.json()
    assert len(stores) == 1
    assert stores[0]["name"] == test_store_data["name"]

@patch('main.ShopifyClient')
def test_delete_store(mock_shopify_client, client, auth_headers, test_store_data):
    """Test deleting a store"""
    # Mock successful store connection
    mock_instance = mock_shopify_client.return_value
    mock_instance.test_connection = AsyncMock(return_value=True)
    mock_instance.get_shop_info = AsyncMock(return_value={
        "name": "Test Store",
        "domain": "test-store.myshopify.com"
    })
    
    # Add store
    response = client.post("/stores", json=test_store_data, headers=auth_headers)
    store_id = response.json()["id"]
    
    # Delete store
    response = client.delete(f"/stores/{store_id}", headers=auth_headers)
    assert response.status_code == 200
    
    # Verify it's deleted
    response = client.get("/stores", headers=auth_headers)
    assert response.json() == []

def test_delete_nonexistent_store(client, auth_headers):
    """Test deleting a non-existent store"""
    response = client.delete("/stores/999", headers=auth_headers)
    assert response.status_code == 404