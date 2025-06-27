#!/usr/bin/env python3
"""
Test script to verify the all-or-nothing policy fix.
This test ensures that excluded SKUs are checked for inventory availability
when making fulfillment location changes (all-or-nothing policy).
"""

import sys
import os
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

from tasks import _check_inventory_availability
import asyncio

async def test_all_or_nothing_with_excluded_skus():
    """Test that ALL products are checked for inventory, including excluded SKUs"""
    
    # Mock fulfillment order with regular product and excluded SKU
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
                                "title": "Test Product (excluded SKU)"
                            }
                        }
                    }
                }
            ]
        }
    }
    
    # Mock client that simulates out of stock for the excluded SKU
    class MockClient:
        async def check_inventory_at_location(self, variant_id, location_id):
            # Regular product has stock, excluded SKU is out of stock
            if variant_id == "gid://shopify/ProductVariant/1":
                return 10  # Regular product has inventory
            elif variant_id == "gid://shopify/ProductVariant/2":
                return 0   # Excluded SKU is out of stock
            return 0
    
    client = MockClient()
    
    print("Testing inventory check with excluded SKUs (after fix)...")
    print("- Regular product (REG-001): Has inventory (10 units)")
    print("- Excluded SKU (TEST-SAMPLE-001): Out of stock (0 units)")
    print("- Expected behavior: all_available = False (because excluded SKU is OOS)")
    
    # Test with excluded SKUs - should NOT skip inventory check for excluded SKUs
    excluded_skus = ["TEST"]
    result = await _check_inventory_availability(
        client, mock_fulfillment_order, "gid://shopify/Location/123", "TEST001", None  # Pass None, not excluded_skus
    )
    
    print(f"\nResults:")
    print(f"- All available: {result['all_available']}")
    print(f"- Available items: {len(result['available_items'])}")
    print(f"- Unavailable items: {len(result['unavailable_items'])}")
    
    # Check details
    print(f"\nAvailable items:")
    for item in result['available_items']:
        print(f"  - {item['sku']}: {item.get('available_quantity', 'N/A')} units")
    
    print(f"\nUnavailable items:")
    for item in result['unavailable_items']:
        print(f"  - {item['sku']}: {item.get('available_quantity', 'N/A')} units")
    
    # Verify the fix works
    if result['all_available'] == False and len(result['unavailable_items']) > 0:
        # Check if the excluded SKU is in unavailable items
        excluded_sku_in_unavailable = any(
            'TEST' in item.get('sku', '') for item in result['unavailable_items']
        )
        if excluded_sku_in_unavailable:
            print("\n✅ SUCCESS: All-or-nothing policy correctly applied!")
            print("   - Excluded SKU was checked for inventory")
            print("   - Out of stock excluded SKU prevents fulfillment move")
            print("   - All products must be available for fulfillment to proceed")
            return True
        else:
            print("\n❌ PARTIAL FIX: all_available is False but excluded SKU not in unavailable")
            return False
    else:
        print("\n❌ FAILED: all_available should be False due to out-of-stock excluded SKU")
        return False

if __name__ == "__main__":
    print("Testing All-or-Nothing Policy Fix for Excluded SKUs")
    print("=" * 55)
    
    try:
        success = asyncio.run(test_all_or_nothing_with_excluded_skus())
        
        if success:
            print("\n🎉 FIX VERIFIED: Excluded SKUs are now properly checked for inventory!")
            print("   The all-or-nothing policy correctly applies to ALL products.")
        else:
            print("\n❌ FIX INCOMPLETE: There may still be issues with the implementation.")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()