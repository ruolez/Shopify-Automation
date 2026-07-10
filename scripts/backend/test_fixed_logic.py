#!/usr/bin/env python3
"""
Test the fixed previous order logic
"""
import sys
import os
import asyncio

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

async def test_fixed_logic():
    """Test the fixed previous order logic"""
    
    print("🔧 TESTING FIXED PREVIOUS ORDER LOGIC")
    print("=" * 50)
    
    try:
        from database import get_db
        from models import User, ShopifyStore, FraudAnalysis
        from fraud_service import FraudAnalysisService
        from shopify_client import ShopifyClient
        
        db = next(get_db())
        
        # Get the user and store
        user = db.query(User).filter(User.email == 'alexr@tobaccogeneral.com').first()
        store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
        
        # Delete existing analysis for fresh test
        existing = db.query(FraudAnalysis).filter(FraudAnalysis.order_name == 'PW15996').first()
        if existing:
            db.delete(existing)
            db.commit()
            print("🗑️  Deleted existing analysis for fresh test")
        
        # Create fraud service and client
        fraud_service = FraudAnalysisService(db, store, user)
        client = ShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        # Get order data for PW15996
        order_data = await client.get_order_fraud_data('PW15996')
        
        if not order_data:
            print("❌ Could not fetch order data")
            return
            
        print("✅ Order data fetched")
        
        # Test the fixed previous order logic
        print(f"\n🔍 TESTING FIXED _get_previous_order_data...")
        prev_status, prev_total = fraud_service._get_previous_order_data(order_data)
        
        print(f"Fixed logic result:")
        print(f"   Previous delivery status: '{prev_status}'")
        print(f"   Previous order total: ${prev_total}")
        
        # Run full analysis to see the final result
        print(f"\n🔄 RUNNING FULL ANALYSIS...")
        analysis = fraud_service.analyze_order_fraud(order_data)
        
        if analysis:
            print(f"✅ ANALYSIS COMPLETE:")
            print(f"   Analysis ID: {analysis.id}")
            print(f"   Order: {analysis.order_name}")
            print(f"   Previous Delivery Status: '{analysis.previous_order_delivery_status}'")
            print(f"   Current Delivery Status: '{analysis.current_order_delivery_status}'")
            
            # Check the result
            if analysis.previous_order_delivery_status and 'april' in analysis.previous_order_delivery_status.lower():
                print(f"\n✅ SUCCESS: Now showing ACTUAL previous order delivery (April)!")
                print(f"   This should be PW14149 delivery status, not PW15996!")
            elif analysis.previous_order_delivery_status and 'august' in analysis.previous_order_delivery_status.lower():
                print(f"\n❌ STILL WRONG: Still showing current order delivery (August)")
            elif analysis.previous_order_delivery_status is None:
                print(f"\n⚠️  No previous delivery status found")
            else:
                print(f"\n🤔 Unexpected result: '{analysis.previous_order_delivery_status}'")
        else:
            print("❌ Analysis failed")
            
    except Exception as e:
        print(f"❌ Error testing fixed logic: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎉 Fixed Logic Test Complete!")
    print("=" * 35)

if __name__ == "__main__":
    asyncio.run(test_fixed_logic())