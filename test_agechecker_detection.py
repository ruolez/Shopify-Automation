#!/usr/bin/env python3
"""Test script to verify AgeChecker detection patterns"""

# Test the pattern matching logic
age_verification_patterns = ['agechecker', 'age-checker']

test_cases = [
    "AgeChecker",
    "agechecker",
    "age-checker",
    "Age-Checker",
    "AGECHECKER",
    "ageChecker",
    "Age Checker",  # This one shouldn't match (has space)
    "AgeChecker verification done",
    "Age Verified - AgeChecker.Net UUID: 12345-6789"
]

print("Testing age checker pattern detection:")
print("-" * 50)

for test_value in test_cases:
    test_lower = test_value.lower()
    matched = False
    matched_pattern = None
    
    for pattern in age_verification_patterns:
        if pattern in test_lower:
            matched = True
            matched_pattern = pattern
            break
    
    print(f"Value: '{test_value}'")
    print(f"Lowercase: '{test_lower}'")
    print(f"Match: {'YES' if matched else 'NO'}")
    if matched:
        print(f"Matched pattern: '{matched_pattern}'")
    print("-" * 50)