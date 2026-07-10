#!/usr/bin/env python3

import sys
import os
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

from rule_engine import RuleEngine

def test_weight_calculation_with_excluded_skus():
    """Test that weight calculation excludes specified SKUs"""
    
    # Mock order data with mixed products
    mock_order = {
        "name": "TEST001",
        "currentTotalWeight": 500,  # Total weight including excluded products
        "lineItems": {
            "edges": [
                {
                    "node": {
                        "title": "Regular Product",
                        "quantity": 1,
                        "variant": {
                            "sku": "REG-001",
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
                        "title": "Test Product (should be excluded)",
                        "quantity": 1,
                        "variant": {
                            "sku": "TEST-SAMPLE-001",
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
    
    # Test without excluded SKUs
    rule_engine = RuleEngine()
    weight_without_exclusion = rule_engine._get_order_field_value("order_weight", mock_order)
    print(f"Weight without exclusion: {weight_without_exclusion}g")
    
    # Test with excluded SKUs
    excluded_skus = ["TEST"]
    weight_with_exclusion = rule_engine._get_order_field_value("order_weight", mock_order, excluded_skus)
    print(f"Weight with TEST exclusion: {weight_with_exclusion}g")
    
    # Verify the exclusion worked
    if weight_with_exclusion < weight_without_exclusion:
        print("✅ SUCCESS: Excluded SKUs were properly filtered from weight calculation")
        print(f"   Excluded weight: {weight_without_exclusion - weight_with_exclusion}g")
    else:
        print("❌ FAILED: Excluded SKUs were not filtered from weight calculation")
    
    return weight_with_exclusion, weight_without_exclusion

if __name__ == "__main__":
    print("Testing SKU exclusion in weight calculations...")
    print("=" * 50)
    
    try:
        weight_excluded, weight_total = test_weight_calculation_with_excluded_skus()
        
        print("\nTest Results:")
        print(f"- Total weight (all products): {weight_total}g")
        print(f"- Weight excluding TEST SKUs: {weight_excluded}g")
        print(f"- Weight difference: {weight_total - weight_excluded}g")
        
        if weight_excluded == 200 and weight_total == 500:
            print("\n🎉 All tests passed! SKU exclusion is working correctly.")
        else:
            print(f"\n⚠️  Unexpected results. Expected excluded weight: 200g, total: 500g")
            
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()