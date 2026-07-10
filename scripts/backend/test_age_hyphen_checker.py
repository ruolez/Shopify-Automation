#!/usr/bin/env python3
"""Test specifically for age-checker with hyphen detection"""

# Test the exact pattern matching logic
age_verification_patterns = ['agechecker', 'age-checker']

test_values = [
    "age-checker",
    "Age-Checker", 
    "AGE-CHECKER",
    "age-checker verified",
    "verified with age-checker",
    "age-checker.net",
    "Age-Checker.Net UUID: 12345",
]

print("Testing age-checker (with hyphen) detection:")
print("=" * 60)
print(f"Patterns being checked: {age_verification_patterns}")
print("=" * 60)

for test_value in test_values:
    test_lower = test_value.lower()
    matched = False
    matched_pattern = None
    
    for pattern in age_verification_patterns:
        if pattern in test_lower:
            matched = True
            matched_pattern = pattern
            break
    
    print(f"\nOriginal: '{test_value}'")
    print(f"Lowercase: '{test_lower}'")
    print(f"Result: {'✅ MATCHED' if matched else '❌ NOT MATCHED'}")
    if matched:
        print(f"Matched pattern: '{matched_pattern}'")
        print(f"Pattern '{matched_pattern}' found at position: {test_lower.find(matched_pattern)}")