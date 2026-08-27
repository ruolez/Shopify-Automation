import pytest
from unittest.mock import patch

def test_get_rule_schema(client, auth_headers):
    """Test getting rule schema"""
    response = client.get("/rules/schema", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "fields" in data
    assert "operators" in data
    assert "action_types" in data
    assert len(data["fields"]) > 0
    assert len(data["operators"]) > 0
    assert len(data["action_types"]) > 0
    field_types = {f["field"]: f["type"] for f in data["fields"]}
    assert {
        "order_profit": field_types.get("order_profit"),
        "order_profit_margin": field_types.get("order_profit_margin"),
        "line_items_missing_cost": field_types.get("line_items_missing_cost"),
    } == {"order_profit": "number", "order_profit_margin": "number", "line_items_missing_cost": "number"}

def test_get_rules_empty(client, auth_headers):
    """Test getting rules when none exist"""
    response = client.get("/rules", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []

def test_create_rule_success(client, auth_headers, test_rule_data):
    """Test creating a new rule successfully"""
    response = client.post("/rules", json=test_rule_data, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == test_rule_data["name"]
    assert data["description"] == test_rule_data["description"]
    assert data["priority"] == test_rule_data["priority"]
    assert data["is_active"] == test_rule_data["is_active"]
    assert "id" in data

def test_create_rule_invalid_data(client, auth_headers):
    """Test creating rule with invalid data"""
    invalid_rule = {
        "name": "",  # Empty name should fail
        "conditions": [],  # Empty conditions should fail
        "actions": [],  # Empty actions should fail
        "priority": -1,  # Invalid priority
        "is_active": True
    }
    
    response = client.post("/rules", json=invalid_rule, headers=auth_headers)
    assert response.status_code == 422  # Validation error

def test_get_rules_with_data(client, auth_headers, test_rule_data):
    """Test getting rules after creating one"""
    # Create rule
    client.post("/rules", json=test_rule_data, headers=auth_headers)
    
    # Get rules
    response = client.get("/rules", headers=auth_headers)
    assert response.status_code == 200
    rules = response.json()
    assert len(rules) == 1
    assert rules[0]["name"] == test_rule_data["name"]

def test_get_rule_by_id(client, auth_headers, test_rule_data):
    """Test getting a specific rule by ID"""
    # Create rule
    response = client.post("/rules", json=test_rule_data, headers=auth_headers)
    rule_id = response.json()["id"]
    
    # Get rule by ID
    response = client.get(f"/rules/{rule_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == test_rule_data["name"]

def test_get_nonexistent_rule(client, auth_headers):
    """Test getting a non-existent rule"""
    response = client.get("/rules/999", headers=auth_headers)
    assert response.status_code == 404

def test_update_rule(client, auth_headers, test_rule_data):
    """Test updating a rule"""
    # Create rule
    response = client.post("/rules", json=test_rule_data, headers=auth_headers)
    rule_id = response.json()["id"]
    
    # Update rule
    updated_data = test_rule_data.copy()
    updated_data["name"] = "Updated Test Rule"
    updated_data["priority"] = 5
    
    response = client.put(f"/rules/{rule_id}", json=updated_data, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Test Rule"
    assert data["priority"] == 5

def test_delete_rule(client, auth_headers, test_rule_data):
    """Test deleting a rule"""
    # Create rule
    response = client.post("/rules", json=test_rule_data, headers=auth_headers)
    rule_id = response.json()["id"]
    
    # Delete rule
    response = client.delete(f"/rules/{rule_id}", headers=auth_headers)
    assert response.status_code == 200
    
    # Verify it's deleted
    response = client.get("/rules", headers=auth_headers)
    assert response.json() == []

def test_delete_nonexistent_rule(client, auth_headers):
    """Test deleting a non-existent rule"""
    response = client.delete("/rules/999", headers=auth_headers)
    assert response.status_code == 404

def test_create_rule_legacy_format(client, auth_headers, test_rule_data_legacy):
    """Test creating a rule with legacy format (backward compatibility)"""
    response = client.post("/rules", json=test_rule_data_legacy, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    
    # Should be converted to new format
    assert "conditions" in data
    assert isinstance(data["conditions"], dict)
    assert "operator" in data["conditions"]
    assert data["conditions"]["operator"] == "AND"
    assert "conditions" in data["conditions"]
    assert isinstance(data["conditions"]["conditions"], list)

def test_create_rule_or_logic(client, auth_headers, test_rule_data_or):
    """Test creating a rule with OR logic"""
    response = client.post("/rules", json=test_rule_data_or, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    
    assert data["name"] == test_rule_data_or["name"]
    assert data["conditions"]["operator"] == "OR"
    assert len(data["conditions"]["conditions"]) == 2

def test_rule_format_validation(client, auth_headers):
    """Test validation of rule condition formats"""
    # Test invalid operator
    invalid_rule = {
        "name": "Invalid Rule",
        "conditions": {
            "operator": "INVALID",
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
                "parameters": {"tags": "test"}
            }
        ],
        "priority": 1,
        "is_active": True
    }
    
    response = client.post("/rules", json=invalid_rule, headers=auth_headers)
    assert response.status_code == 422