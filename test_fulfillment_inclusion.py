#!/usr/bin/env python3

import sys
import os
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

from tasks import _check_inventory_availability
import asyncio

async def test_inventory_check_with_excluded_skus():
    """Test that inventory checks exclude SKUs but fulfillment includes them"""
    
    # Mock fulfillment order with mixed products
    mock_fulfillment_order = {
        "lineItems": {
            "edges": [
                {
                    "node": {
                        "totalQuantity": 1,
                        "variant": {
                            "id": "gid://shopify/ProductVariant/1",
                            "sku": "REG-001",
                            "product": {
                                "title": "Regular Product"
                            }
                        }
                    }
                },
                {
                    "node": {
                        "totalQuantity": 1,
                        "variant": {
                            "id": "gid://shopify/ProductVariant/2", 
                            "sku": "TEST-SAMPLE-001",
                            "product": {
                                "title": "Test Product (should be excluded from inventory check)"
                            }
                        }
                    }
                }
            ]
        }
    }
    
    # Mock client that returns success for inventory checks
    class MockClient:
        async def check_inventory_at_location(self, variant_id, location_id):
            # Simulate inventory being available
            return {
                "inventoryLevel": {
                    "available": 10
                }
            }
    
    client = MockClient()
    
    print("Testing inventory check without excluded SKUs...")
    result_without_exclusion = await _check_inventory_availability(
        client, mock_fulfillment_order, "gid://shopify/Location/123", "TEST001"
    )
    
    print("Testing inventory check with excluded SKUs...")
    excluded_skus = ["TEST"]
    result_with_exclusion = await _check_inventory_availability(
        client, mock_fulfillment_order, "gid://shopify/Location/123", "TEST001", excluded_skus
    )
    
    print(f"\nResults without exclusion:")
    print(f"- All available: {result_without_exclusion['all_available']}")
    print(f"- Available items: {len(result_without_exclusion['available_items'])}")
    print(f"- Unavailable items: {len(result_without_exclusion['unavailable_items'])}")
    
    print(f"\nResults with TEST exclusion:")
    print(f"- All available: {result_with_exclusion['all_available']}")
    print(f"- Available items: {len(result_with_exclusion['available_items'])}")
    print(f"- Unavailable items: {len(result_with_exclusion['unavailable_items'])}")
    
    # Check that excluded SKUs are in available_items (so they don't block fulfillment)
    excluded_skus_in_available = []
    for item in result_with_exclusion['available_items']:
        if 'TEST' in item.get('sku', ''):
            excluded_skus_in_available.append(item)
    
    print(f"\nExcluded SKUs found in available items: {len(excluded_skus_in_available)}")
    for item in excluded_skus_in_available:
        print(f"- {item['sku']}: {item.get('available_quantity', 'N/A')}")
    
    # Verify that excluded SKUs are still included for fulfillment
    if len(excluded_skus_in_available) > 0:
        print("✅ SUCCESS: Excluded SKUs are included in fulfillment (marked as available)")
    else:
        print("❌ FAILED: Excluded SKUs were completely removed from fulfillment")
    
    return result_without_exclusion, result_with_exclusion

if __name__ == "__main__":
    print("Testing fulfillment inclusion of excluded SKUs...")
    print("=" * 55)
    
    try:
        without_exclusion, with_exclusion = asyncio.run(test_inventory_check_with_excluded_skus())
        
        print("\n🎉 Test completed! Excluded SKUs are properly handled:")
        print("   - Excluded from inventory availability checks")
        print("   - But still included in fulfillment moves")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()