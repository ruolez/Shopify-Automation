#!/usr/bin/env python3
"""
Test the API endpoint directly without authentication to check serialization
"""
import sys
import os
import json

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

def test_api_serialization():
    """Test the API serialization directly"""
    
    print("🔍 TESTING API SERIALIZATION DIRECTLY")
    print("=" * 50)
    
    try:
        from database import get_db
        from models import FraudAnalysis, ShopifyStore
        
        db = next(get_db())
        
        # Get analysis ID 2 directly
        analysis = db.query(FraudAnalysis).filter(FraudAnalysis.id == 2).first()
        
        if not analysis:
            print("❌ Analysis ID 2 not found")
            return
            
        # Get store name
        store = db.query(ShopifyStore).filter(ShopifyStore.id == analysis.store_id).first()
        store_name = store.shop_name if store else "Unknown Store"
        
        print(f"✅ Found analysis ID 2")
        print(f"   Order: {analysis.order_name}")
        print(f"   Store: {store_name}")
        
        # Test the exact serialization that the API endpoint uses
        api_response = {
            "analysis": {
                "id": analysis.id,
                "user_id": analysis.user_id,
                "store_id": analysis.store_id,
                "order_name": analysis.order_name,
                "shopify_order_id": analysis.shopify_order_id,
                "is_first_time_customer": analysis.is_first_time_customer,
                "order_total": float(analysis.order_total) if analysis.order_total else None,
                "transaction_attempts_count": analysis.transaction_attempts_count,
                "card_holder_name": analysis.card_holder_name,
                "duplicate_within_7days": analysis.duplicate_within_7days,
                "previous_order_delivery_status": analysis.previous_order_delivery_status,
                "previous_order_total": float(analysis.previous_order_total) if analysis.previous_order_total else None,
                "current_order_total": float(analysis.current_order_total) if analysis.current_order_total else None,
                "shopify_fraud_risk_level": analysis.shopify_fraud_risk_level,
                "age_checker_detected": analysis.age_checker_detected,
                "customer_notes": analysis.customer_notes,
                "billing_address_outside_us": analysis.billing_address_outside_us,
                "additional_details": analysis.additional_details,
                "current_order_delivery_status": analysis.current_order_delivery_status,
                "raw_shopify_data": analysis.raw_shopify_data,
                "duplicate_match_details": analysis.duplicate_match_details,
                "transaction_details": analysis.transaction_details,
                "risk_assessment_details": analysis.risk_assessment_details,
                "customer_order_history": analysis.customer_order_history,
                "analysis_timestamp": analysis.analysis_timestamp.isoformat() if analysis.analysis_timestamp else None,
                "processing_time_seconds": float(analysis.processing_time_seconds) if analysis.processing_time_seconds else None,
                "analysis_version": analysis.analysis_version
            },
            "store_name": store_name
        }
        
        print(f"\n📊 API SERIALIZATION TEST:")
        print(f"   Previous Delivery Status: '{api_response['analysis']['previous_order_delivery_status']}'")
        print(f"   Current Delivery Status: '{api_response['analysis']['current_order_delivery_status']}'")
        print(f"   Type: {type(api_response['analysis']['previous_order_delivery_status'])}")
        
        # Check for the August 5th data
        prev_status = api_response['analysis']['previous_order_delivery_status']
        if prev_status is None:
            print(f"\n❌ ISSUE: previous_order_delivery_status is None")
        elif prev_status == "":
            print(f"\n❌ ISSUE: previous_order_delivery_status is empty string")
        elif 'august' in prev_status.lower() and '2024' in prev_status:
            print(f"\n✅ SUCCESS: August 2024 delivery data in API serialization!")
        else:
            print(f"\n⚠️  Unexpected value: '{prev_status}'")
        
        # Show the JSON that would be sent to frontend
        print(f"\n📄 SERIALIZED JSON (what frontend should receive):")
        print("=" * 55)
        # Just show the relevant parts
        relevant_data = {
            "analysis": {
                "id": api_response['analysis']['id'],
                "order_name": api_response['analysis']['order_name'],
                "previous_order_delivery_status": api_response['analysis']['previous_order_delivery_status'],
                "current_order_delivery_status": api_response['analysis']['current_order_delivery_status'],
                "is_first_time_customer": api_response['analysis']['is_first_time_customer']
            },
            "store_name": api_response['store_name']
        }
        print(json.dumps(relevant_data, indent=2))
        
        # Test if there's an issue with the database field access
        print(f"\n🔍 DIRECT DATABASE FIELD ACCESS:")
        print(f"   analysis.previous_order_delivery_status = '{analysis.previous_order_delivery_status}'")
        print(f"   analysis.current_order_delivery_status = '{analysis.current_order_delivery_status}'")
        print(f"   Raw type: {type(analysis.previous_order_delivery_status)}")
        
        # Check if delivery_analytics field exists and has data
        if hasattr(analysis, 'delivery_analytics'):
            print(f"\n📊 DELIVERY ANALYTICS FIELD:")
            print(f"   delivery_analytics exists: {analysis.delivery_analytics is not None}")
            if analysis.delivery_analytics:
                try:
                    analytics = analysis.delivery_analytics
                    if isinstance(analytics, dict):
                        prev_status_analytics = analytics.get('previous_order_delivery_status')
                        print(f"   analytics.previous_order_delivery_status: '{prev_status_analytics}'")
                    else:
                        print(f"   delivery_analytics type: {type(analytics)}")
                except Exception as e:
                    print(f"   Error accessing delivery_analytics: {e}")
        else:
            print(f"\n❌ delivery_analytics field does not exist")
        
    except Exception as e:
        print(f"❌ Error testing API serialization: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎉 API Serialization Test Complete!")
    print("=" * 40)

if __name__ == "__main__":
    test_api_serialization()