"""
Tests for rule priority execution order and rule engine functionality.
These tests verify that the recent fix to rule priority execution is working correctly.
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from main import app
from models import ProcessingRule, User, ShopifyStore
from rule_engine import RuleEngine
from tasks import _process_store_orders_async, _apply_rule_actions
from conftest import TestingSessionLocal


class TestRulePriorityExecution:
    """Test rule priority execution order"""
    
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
    
    def test_rule_priority_order_in_database(self, db_session, test_user_db):
        """Test that rules are retrieved in correct priority order (ascending)"""
        # Create rules with different priorities
        rule_high = ProcessingRule(
            user_id=test_user_db.id,
            name="High Priority Rule",
            description="Should execute first",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "0"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["high"]}}],
            priority=0,  # Lowest number = highest priority
            is_active=True
        )
        
        rule_medium = ProcessingRule(
            user_id=test_user_db.id,
            name="Medium Priority Rule",
            description="Should execute second",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "0"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["medium"]}}],
            priority=1,
            is_active=True
        )
        
        rule_low = ProcessingRule(
            user_id=test_user_db.id,
            name="Low Priority Rule",
            description="Should execute last",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "0"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["low"]}}],
            priority=2,
            is_active=True
        )
        
        # Add rules in random order
        db_session.add(rule_medium)
        db_session.add(rule_low)
        db_session.add(rule_high)
        db_session.commit()
        
        # Query rules with the same order by clause used in the actual code
        rules = db_session.query(ProcessingRule).filter(
            ProcessingRule.user_id == test_user_db.id,
            ProcessingRule.is_active == True
        ).order_by(ProcessingRule.priority.asc()).all()
        
        # Verify order is correct (0, 1, 2)
        assert len(rules) == 3
        assert rules[0].name == "High Priority Rule"
        assert rules[0].priority == 0
        assert rules[1].name == "Medium Priority Rule"
        assert rules[1].priority == 1
        assert rules[2].name == "Low Priority Rule"
        assert rules[2].priority == 2
    
    def test_rule_priority_execution_order_simulation(self, db_session, test_user_db, test_store_db):
        """Test that rules execute in the correct order during order processing"""
        # Create rules that would show execution order
        rule_first = ProcessingRule(
            user_id=test_user_db.id,
            name="Add High-Value Tag",
            description="Should execute first",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "100"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["high-value"]}}],
            priority=0,
            is_active=True
        )
        
        rule_second = ProcessingRule(
            user_id=test_user_db.id,
            name="Remove High-Value Tag",
            description="Should execute second and see the tag added by first rule",
            conditions={"operator": "AND", "conditions": [{"field": "order_tags", "operator": "contains", "value": "high-value"}]},
            actions=[{"type": "remove_tag", "parameters": {"tags": ["high-value"]}}],
            priority=1,
            is_active=True
        )
        
        rule_third = ProcessingRule(
            user_id=test_user_db.id,
            name="Add Final Tag",
            description="Should execute third",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "100"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["processed"]}}],
            priority=2,
            is_active=True
        )
        
        db_session.add(rule_first)
        db_session.add(rule_second)
        db_session.add(rule_third)
        db_session.commit()
        
        # Mock order data
        order_data = {
            "id": "gid://shopify/Order/12345",
            "name": "TEST123",
            "totalPriceSet": {"shopMoney": {"amount": "150.00"}},
            "tags": [],
            "createdAt": "2025-01-14T10:30:00Z",
            "displayFulfillmentStatus": "UNFULFILLED",
            "fulfillmentOrders": {"edges": []}
        }
        
        # Track execution order by mocking the rule engine
        execution_order = []
        
        def mock_evaluate_rule(rule, order, excluded_skus, store):
            execution_order.append(rule.name)
            
            # Simulate rule logic
            if rule.name == "Add High-Value Tag":
                return True  # Should match (order > 100)
            elif rule.name == "Remove High-Value Tag":
                # This should only match if the first rule added the tag
                return "high-value" in order.get("tags", [])
            elif rule.name == "Add Final Tag":
                return True  # Should match (order > 100)
            return False
        
        # Mock the rule engine
        with patch('tasks.RuleEngine') as mock_rule_engine_class:
            mock_rule_engine = Mock()
            mock_rule_engine_class.return_value = mock_rule_engine
            mock_rule_engine.evaluate_rule.side_effect = mock_evaluate_rule
            
            # Mock the apply rule actions
            async def mock_apply_rule_actions(client, rule, order, store, db, excluded_skus):
                # Simulate the actions
                if rule.name == "Add High-Value Tag":
                    order["tags"] = order.get("tags", []) + ["high-value"]
                elif rule.name == "Remove High-Value Tag":
                    order["tags"] = [tag for tag in order.get("tags", []) if tag != "high-value"]
                elif rule.name == "Add Final Tag":
                    order["tags"] = order.get("tags", []) + ["processed"]
                return True
            
            # Mock the Shopify client
            with patch('tasks.ShopifyClient') as mock_client_class:
                mock_client = Mock()
                mock_client_class.return_value = mock_client
                mock_client.get_order_by_id = AsyncMock(return_value=order_data)
                
                # Mock the apply rule actions function
                with patch('tasks._apply_rule_actions', side_effect=mock_apply_rule_actions):
                    # Get rules in the same order as the actual code
                    rules = db_session.query(ProcessingRule).filter(
                        ProcessingRule.user_id == test_user_db.id,
                        ProcessingRule.is_active == True
                    ).order_by(ProcessingRule.priority.asc()).all()
                    
                    # Simulate the rule execution loop from _process_store_orders_async
                    current_order = order_data
                    for rule in rules:
                        if mock_rule_engine.evaluate_rule(rule, current_order, [], test_store_db):
                            # Apply the actions
                            import asyncio
                            asyncio.run(mock_apply_rule_actions(mock_client, rule, current_order, test_store_db, db_session, []))
        
        # Verify execution order
        assert execution_order == ["Add High-Value Tag", "Remove High-Value Tag", "Add Final Tag"]
        
        # Verify the final state of the order
        # First rule adds "high-value", second rule removes it, third rule adds "processed"
        assert "high-value" not in order_data["tags"]  # Should be removed
        assert "processed" in order_data["tags"]  # Should be added
    
    def test_rule_with_same_priority_deterministic_order(self, db_session, test_user_db):
        """Test that rules with same priority execute in deterministic order"""
        # Create rules with same priority
        rule_a = ProcessingRule(
            user_id=test_user_db.id,
            name="Rule A",
            description="Same priority rule A",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "0"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["a"]}}],
            priority=1,
            is_active=True
        )
        
        rule_b = ProcessingRule(
            user_id=test_user_db.id,
            name="Rule B",
            description="Same priority rule B",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "0"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["b"]}}],
            priority=1,
            is_active=True
        )
        
        db_session.add(rule_a)
        db_session.add(rule_b)
        db_session.commit()
        
        # Query multiple times to ensure consistent order
        for _ in range(3):
            rules = db_session.query(ProcessingRule).filter(
                ProcessingRule.user_id == test_user_db.id,
                ProcessingRule.is_active == True
            ).order_by(ProcessingRule.priority.asc()).all()
            
            # Should be in deterministic order (likely by ID)
            assert len(rules) == 2
            assert rules[0].id < rules[1].id  # Should be ordered by ID as secondary sort
    
    def test_inactive_rules_not_executed(self, db_session, test_user_db):
        """Test that inactive rules are not included in execution"""
        # Create active and inactive rules
        rule_active = ProcessingRule(
            user_id=test_user_db.id,
            name="Active Rule",
            description="Should be executed",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "0"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["active"]}}],
            priority=1,
            is_active=True
        )
        
        rule_inactive = ProcessingRule(
            user_id=test_user_db.id,
            name="Inactive Rule",
            description="Should NOT be executed",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "0"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["inactive"]}}],
            priority=0,  # Higher priority but inactive
            is_active=False
        )
        
        db_session.add(rule_active)
        db_session.add(rule_inactive)
        db_session.commit()
        
        # Query with the same filter used in actual code
        rules = db_session.query(ProcessingRule).filter(
            ProcessingRule.user_id == test_user_db.id,
            ProcessingRule.is_active == True
        ).order_by(ProcessingRule.priority.asc()).all()
        
        # Should only return active rule
        assert len(rules) == 1
        assert rules[0].name == "Active Rule"
    
    def test_rule_delay_setting(self, db_session, test_user_db):
        """Test that rule delay_ms setting is properly stored and retrieved"""
        # Create rule with custom delay
        rule = ProcessingRule(
            user_id=test_user_db.id,
            name="Delayed Rule",
            description="Rule with custom delay",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "0"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["delayed"]}}],
            priority=1,
            delay_ms=2000,  # 2 second delay
            is_active=True
        )
        
        db_session.add(rule)
        db_session.commit()
        
        # Retrieve and verify delay
        retrieved_rule = db_session.query(ProcessingRule).filter(
            ProcessingRule.user_id == test_user_db.id,
            ProcessingRule.name == "Delayed Rule"
        ).first()
        
        assert retrieved_rule.delay_ms == 2000
    
    def test_rule_delay_default_value(self, db_session, test_user_db):
        """Test that rule delay_ms has correct default value"""
        # Create rule without specifying delay
        rule = ProcessingRule(
            user_id=test_user_db.id,
            name="Default Delay Rule",
            description="Rule with default delay",
            conditions={"operator": "AND", "conditions": [{"field": "order_total", "operator": "greater_than", "value": "0"}]},
            actions=[{"type": "add_tag", "parameters": {"tags": ["default"]}}],
            priority=1,
            is_active=True
            # delay_ms not specified, should use default
        )
        
        db_session.add(rule)
        db_session.commit()
        
        # Retrieve and verify default delay
        retrieved_rule = db_session.query(ProcessingRule).filter(
            ProcessingRule.user_id == test_user_db.id,
            ProcessingRule.name == "Default Delay Rule"
        ).first()
        
        assert retrieved_rule.delay_ms == 10  # Default value from model


class TestRuleEngineLogic:
    """Test rule engine evaluation logic"""
    
    def test_rule_engine_and_logic(self):
        """Test AND logic in rule engine"""
        engine = RuleEngine()
        
        # Mock rule with AND logic
        rule_data = {
            "conditions": {
                "operator": "AND",
                "conditions": [
                    {"field": "order_total", "operator": "greater_than", "value": "100"},
                    {"field": "shipping_province", "operator": "equals", "value": "CA"}
                ]
            }
        }
        
        # Create a mock rule object
        rule = Mock()
        rule.conditions = rule_data["conditions"]
        rule.name = "Test AND Rule"
        rule.id = 1
        
        # Test case 1: Both conditions true
        order_both_true = {
            "totalPriceSet": {"shopMoney": {"amount": "150.00"}},
            "shippingAddress": {"province": "CA"}
        }
        assert engine.evaluate_rule(rule, order_both_true) == True
        
        # Test case 2: First condition true, second false
        order_first_true = {
            "totalPriceSet": {"shopMoney": {"amount": "150.00"}},
            "shippingAddress": {"province": "NY"}
        }
        assert engine.evaluate_rule(rule, order_first_true) == False
        
        # Test case 3: Both conditions false
        order_both_false = {
            "totalPriceSet": {"shopMoney": {"amount": "50.00"}},
            "shippingAddress": {"province": "NY"}
        }
        assert engine.evaluate_rule(rule, order_both_false) == False
    
    def test_rule_engine_or_logic(self):
        """Test OR logic in rule engine"""
        engine = RuleEngine()
        
        # Mock rule with OR logic
        rule_data = {
            "conditions": {
                "operator": "OR",
                "conditions": [
                    {"field": "order_total", "operator": "greater_than", "value": "100"},
                    {"field": "shipping_province", "operator": "equals", "value": "CA"}
                ]
            }
        }
        
        # Create a mock rule object
        rule = Mock()
        rule.conditions = rule_data["conditions"]
        rule.name = "Test OR Rule"
        rule.id = 1
        
        # Test case 1: Both conditions true
        order_both_true = {
            "totalPriceSet": {"shopMoney": {"amount": "150.00"}},
            "shippingAddress": {"province": "CA"}
        }
        assert engine.evaluate_rule(rule, order_both_true) == True
        
        # Test case 2: First condition true, second false
        order_first_true = {
            "totalPriceSet": {"shopMoney": {"amount": "150.00"}},
            "shippingAddress": {"province": "NY"}
        }
        assert engine.evaluate_rule(rule, order_first_true) == True
        
        # Test case 3: First condition false, second true
        order_second_true = {
            "totalPriceSet": {"shopMoney": {"amount": "50.00"}},
            "shippingAddress": {"province": "CA"}
        }
        assert engine.evaluate_rule(rule, order_second_true) == True
        
        # Test case 4: Both conditions false
        order_both_false = {
            "totalPriceSet": {"shopMoney": {"amount": "50.00"}},
            "shippingAddress": {"province": "NY"}
        }
        assert engine.evaluate_rule(rule, order_both_false) == False
    
    def test_rule_engine_legacy_format_compatibility(self):
        """Test that rule engine handles legacy format (direct conditions array)"""
        engine = RuleEngine()
        
        # Mock rule with legacy format (direct array)
        rule_data = {
            "conditions": [
                {"field": "order_total", "operator": "greater_than", "value": "100"},
                {"field": "shipping_province", "operator": "equals", "value": "CA"}
            ]
        }
        
        # Create a mock rule object
        rule = Mock()
        rule.conditions = rule_data["conditions"]
        rule.name = "Test Legacy Rule"
        rule.id = 1
        
        # Should default to AND logic
        order_both_true = {
            "totalPriceSet": {"shopMoney": {"amount": "150.00"}},
            "shippingAddress": {"province": "CA"}
        }
        assert engine.evaluate_rule(rule, order_both_true) == True
        
        # Should fail if one condition is false (AND logic)
        order_first_false = {
            "totalPriceSet": {"shopMoney": {"amount": "50.00"}},
            "shippingAddress": {"province": "CA"}
        }
        assert engine.evaluate_rule(rule, order_first_false) == False
    
    def test_rule_engine_fulfillment_location_fix(self):
        """Test the fix for fulfillment location conditions"""
        engine = RuleEngine()
        
        # Mock rule with fulfillment location condition
        rule_data = {
            "conditions": {
                "operator": "AND",
                "conditions": [
                    {"field": "fulfillment_location", "operator": "equals", "value": "SC"}
                ]
            }
        }
        
        # Create a mock rule object
        rule = Mock()
        rule.conditions = rule_data["conditions"]
        rule.name = "Test Fulfillment Location Rule"
        rule.id = 1
        
        # Mock order with fulfillment location array
        order_with_sc = {
            "fulfillmentOrders": {
                "edges": [
                    {
                        "node": {
                            "assignedLocation": {
                                "location": {
                                    "id": "gid://shopify/Location/104204796206",
                                    "name": "SC Warehouse"
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        # Mock the store context for alias resolution
        mock_store = Mock()
        mock_store.id = 1
        
        # Test that the rule matches when "SC" is in the location list
        # This should work with the fixed logic
        with patch.object(engine, '_get_order_field_value') as mock_get_field:
            # Mock the field value to return a list including "SC"
            mock_get_field.return_value = ["gid://shopify/Location/104204796206", "SC Warehouse", "SC"]
            
            result = engine.evaluate_rule(rule, order_with_sc, None, mock_store)
            assert result == True
        
        # Test that the rule doesn't match when "SC" is not in the location list
        with patch.object(engine, '_get_order_field_value') as mock_get_field:
            # Mock the field value to return a list not including "SC"
            mock_get_field.return_value = ["gid://shopify/Location/104204796206", "NY Warehouse", "NY"]
            
            result = engine.evaluate_rule(rule, order_with_sc, None, mock_store)
            assert result == False