#!/usr/bin/env python3
"""
Test script to demonstrate the days_since_last_delivery feature.

This script shows how the fraud detection system now calculates
days since the previous order's delivery date.
"""
import json
from datetime import datetime, timedelta
from fraud_service import FraudAnalysisService

# Example order data with customer history
test_order_data = {
    "id": "gid://shopify/Order/5678901234567",
    "name": "#1234",
    "createdAt": datetime.now().isoformat() + "Z",
    "customer": {
        "id": "gid://shopify/Customer/123456789",
        "displayName": "John Doe",
        "numberOfOrders": 3,
        "orders": {
            "edges": [
                {
                    "node": {
                        "id": "gid://shopify/Order/5678901234567",
                        "name": "#1234",
                        "createdAt": datetime.now().isoformat() + "Z",
                        "totalPriceSet": {
                            "shopMoney": {"amount": "100.00"}
                        },
                        "fulfillments": []
                    }
                },
                {
                    "node": {
                        "id": "gid://shopify/Order/5678901234566",
                        "name": "#1233",
                        "createdAt": (datetime.now() - timedelta(days=45)).isoformat() + "Z",
                        "totalPriceSet": {
                            "shopMoney": {"amount": "75.00"}
                        },
                        "fulfillments": [
                            {
                                "id": "gid://shopify/Fulfillment/987654321",
                                "deliveredAt": (datetime.now() - timedelta(days=40)).isoformat() + "Z",
                                "displayStatus": "DELIVERED"
                            }
                        ]
                    }
                },
                {
                    "node": {
                        "id": "gid://shopify/Order/5678901234565",
                        "name": "#1232",
                        "createdAt": (datetime.now() - timedelta(days=90)).isoformat() + "Z",
                        "totalPriceSet": {
                            "shopMoney": {"amount": "50.00"}
                        },
                        "fulfillments": [
                            {
                                "id": "gid://shopify/Fulfillment/987654320",
                                "deliveredAt": (datetime.now() - timedelta(days=85)).isoformat() + "Z",
                                "displayStatus": "DELIVERED"
                            }
                        ]
                    }
                }
            ]
        }
    }
}

def test_days_since_delivery_calculation():
    """Test the days since last delivery calculation."""
    print("Testing days_since_last_delivery calculation...")
    print("-" * 50)
    
    # Initialize a mock fraud service (you'd normally use a real DB session)
    service = FraudAnalysisService(None, None, None)
    
    # Test 1: Calculate days since last delivery
    previous_order = test_order_data["customer"]["orders"]["edges"][1]["node"]
    days_since = service._calculate_days_since_last_delivery(test_order_data, previous_order)
    
    print(f"Current order created: Today")
    print(f"Previous order (#1233) delivered: 40 days ago")
    print(f"Days since last delivery: {days_since} days")
    print()
    
    # Test 2: Show how this would be used in a fraud rule
    print("Example fraud rules using days_since_last_delivery:")
    print("-" * 50)
    
    example_rules = [
        {
            "name": "Rapid Reorder Detection",
            "condition": "days_since_last_delivery < 7",
            "action": "flag as potential duplicate order"
        },
        {
            "name": "Returning Customer After Long Gap",
            "condition": "days_since_last_delivery > 365",
            "action": "apply returning customer discount"
        },
        {
            "name": "Suspicious Quick Reorder",
            "condition": "days_since_last_delivery < 30 AND order_total > previous_order_total * 2",
            "action": "require manual fraud review"
        }
    ]
    
    for rule in example_rules:
        print(f"Rule: {rule['name']}")
        print(f"  Condition: {rule['condition']}")
        print(f"  Action: {rule['action']}")
        print()
    
    # Test 3: Show what happens when no previous delivery exists
    print("Edge cases:")
    print("-" * 50)
    
    # First time customer
    first_time_order = {
        "id": "gid://shopify/Order/9999999999999",
        "name": "#9999",
        "createdAt": datetime.now().isoformat() + "Z",
        "customer": {
            "numberOfOrders": 1,
            "orders": {"edges": []}
        }
    }
    
    days_since_first = service._calculate_days_since_last_delivery(first_time_order, None)
    print(f"First-time customer: days_since_last_delivery = {days_since_first}")
    
    # Previous order not delivered
    undelivered_order = {
        "id": "gid://shopify/Order/8888888888888",
        "name": "#8888",
        "fulfillments": []  # No fulfillments
    }
    
    days_since_undelivered = service._calculate_days_since_last_delivery(test_order_data, undelivered_order)
    print(f"Previous order not delivered: days_since_last_delivery = {days_since_undelivered}")

if __name__ == "__main__":
    test_days_since_delivery_calculation()
    print("\nTo use this in production:")
    print("1. Run the migration: python migrations/add_days_since_last_delivery_column.py")
    print("2. Create fraud rules in the UI using 'Days Since Last Delivery' field")
    print("3. The system will automatically calculate this value during fraud analysis")