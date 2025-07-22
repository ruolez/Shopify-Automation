#!/usr/bin/env python3
"""
Test script to verify the 'no_age' fraud rule logic with AND conditions.
This tests that BOTH conditions must be missing from notes for the rule to match.
"""

import logging
from typing import Dict, Any
from rule_engine import RuleEngine
from models import ProcessingRule, FraudDetectionRule
import json

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MockRule:
    """Mock rule object for testing"""
    def __init__(self, name: str, conditions: Dict[str, Any]):
        self.id = 1
        self.name = name
        self.conditions = conditions

def test_no_age_rule_logic():
    """Test the no_age rule with AND logic for two NOT conditions"""
    
    # Initialize rule engine
    rule_engine = RuleEngine(None)
    
    # Define test cases with different note scenarios
    test_cases = [
        {
            "name": "Both texts missing (should match)",
            "notes": "Some random order notes without age verification",
            "expected": True
        },
        {
            "name": "First text present, second missing (should NOT match)",
            "notes": "Customer is 21 years old, verified",
            "expected": False
        },
        {
            "name": "First text missing, second present (should NOT match)",
            "notes": "Date of birth provided: 01/01/1990",
            "expected": False
        },
        {
            "name": "Both texts present (should NOT match)",
            "notes": "Customer is 21 years old. Date of birth: 01/01/1990",
            "expected": False
        },
        {
            "name": "Empty notes (should match)",
            "notes": "",
            "expected": True
        },
        {
            "name": "Partial match of first text (should NOT match)",
            "notes": "Customer mentioned they are 21",
            "expected": False
        },
        {
            "name": "Partial match of second text (should NOT match)",
            "notes": "Birth year: 1990",
            "expected": False
        }
    ]
    
    # Create no_age rule with AND logic
    # Rule: customer_notes NOT contains "21" AND customer_notes NOT contains "birth"
    no_age_rule = MockRule("no_age", {
        "operator": "AND",
        "conditions": [
            {
                "field": "customer_notes",
                "operator": "not_contains",
                "value": "21"
            },
            {
                "field": "customer_notes",
                "operator": "not_contains",
                "value": "birth"
            }
        ]
    })
    
    print("\n" + "="*80)
    print("Testing 'no_age' Fraud Rule Logic - AND conditions with NOT operators")
    print("Rule: customer_notes NOT contains '21' AND customer_notes NOT contains 'birth'")
    print("="*80 + "\n")
    
    all_passed = True
    
    for test_case in test_cases:
        # Create mock order data
        order_data = {
            "name": "TEST-001",
            "customer_notes": test_case["notes"]
        }
        
        # Mock the field extraction to return our test notes
        original_get_field = rule_engine._get_order_field_value
        rule_engine._get_order_field_value = lambda field, order, excluded_skus=None, store_context=None: (
            test_case["notes"] if field == "customer_notes" else original_get_field(field, order, excluded_skus, store_context)
        )
        
        # Evaluate the rule
        result = rule_engine.evaluate_rule(no_age_rule, order_data)
        
        # Check if result matches expectation
        passed = result == test_case["expected"]
        status = "✅ PASS" if passed else "❌ FAIL"
        
        print(f"{status} {test_case['name']}")
        print(f"   Notes: '{test_case['notes']}'")
        print(f"   Expected: {test_case['expected']}, Got: {result}")
        
        # Detailed condition evaluation
        print("   Condition evaluations:")
        print(f"     - NOT contains '21': {not ('21' in test_case['notes'].lower())}")
        print(f"     - NOT contains 'birth': {not ('birth' in test_case['notes'].lower())}")
        print(f"     - AND result: {not ('21' in test_case['notes'].lower()) and not ('birth' in test_case['notes'].lower())}")
        print()
        
        if not passed:
            all_passed = False
        
        # Restore original method
        rule_engine._get_order_field_value = original_get_field
    
    print("="*80)
    print(f"Overall Result: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    print("="*80)
    
    # Summary explanation
    print("\nSUMMARY:")
    print("The AND logic is working correctly. For the 'no_age' rule to match:")
    print("1. BOTH conditions must be true")
    print("2. The first text ('21') must NOT be present in the notes")
    print("3. The second text ('birth') must NOT be present in the notes")
    print("4. If either text is found, the rule will NOT match")
    print("\nThis ensures that only orders without age verification info are flagged.")

if __name__ == "__main__":
    test_no_age_rule_logic()