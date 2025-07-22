#!/usr/bin/env python3
"""
Script to unarchive the test orders that were manually archived.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudAnalysis
from sqlalchemy import text
import json

def unarchive_orders():
    """Unarchive the three test orders."""
    db = SessionLocal()
    
    try:
        # Orders to unarchive
        orders_to_unarchive = ['TSW5737', 'TSW5736', 'TSW5735']
        
        print(f"Unarchiving orders: {', '.join(orders_to_unarchive)}")
        
        for order_name in orders_to_unarchive:
            # Get the archived analysis
            result = db.execute(text("""
                SELECT * FROM fraud_analyses_archive 
                WHERE order_name = :order_name
            """), {"order_name": order_name}).fetchone()
            
            if result:
                print(f"\nProcessing {order_name}...")
                
                # Create a new FraudAnalysis object with all the data
                analysis = FraudAnalysis(
                    id=result.id,
                    user_id=result.user_id,
                    store_id=result.store_id,
                    order_name=result.order_name,
                    shopify_order_id=result.shopify_order_id,
                    
                    # Fraud detection data points
                    is_first_time_customer=result.is_first_time_customer,
                    order_total=result.order_total,
                    transaction_attempts_count=result.transaction_attempts_count,
                    customer_name=result.customer_name,
                    duplicate_within_7days=result.duplicate_within_7days,
                    previous_order_delivery_status=result.previous_order_delivery_status,
                    previous_order_total=result.previous_order_total,
                    current_order_total=result.current_order_total,
                    shopify_fraud_risk_level=result.shopify_fraud_risk_level,
                    age_checker_detected=result.age_checker_detected,
                    customer_notes=result.customer_notes,
                    billing_address_outside_us=result.billing_address_outside_us,
                    same_billing_shipping=result.same_billing_shipping,
                    shipping_state=result.shipping_state,
                    additional_details=result.additional_details,
                    current_order_delivery_status=result.current_order_delivery_status,
                    
                    # Supporting data - parse JSON strings
                    raw_shopify_data=json.loads(result.raw_shopify_data) if result.raw_shopify_data and isinstance(result.raw_shopify_data, str) else result.raw_shopify_data,
                    duplicate_match_details=json.loads(result.duplicate_match_details) if result.duplicate_match_details and isinstance(result.duplicate_match_details, str) else result.duplicate_match_details,
                    transaction_details=json.loads(result.transaction_details) if result.transaction_details and isinstance(result.transaction_details, str) else result.transaction_details,
                    risk_assessment_details=json.loads(result.risk_assessment_details) if result.risk_assessment_details and isinstance(result.risk_assessment_details, str) else result.risk_assessment_details,
                    customer_order_history=json.loads(result.customer_order_history) if result.customer_order_history and isinstance(result.customer_order_history, str) else result.customer_order_history,
                    delivery_analytics=json.loads(result.delivery_analytics) if result.delivery_analytics and isinstance(result.delivery_analytics, str) else result.delivery_analytics,
                    
                    # Fraud rule processing
                    rule_triggered_ids=json.loads(result.rule_triggered_ids) if result.rule_triggered_ids and isinstance(result.rule_triggered_ids, str) else result.rule_triggered_ids,
                    rule_processing_results=json.loads(result.rule_processing_results) if result.rule_processing_results and isinstance(result.rule_processing_results, str) else result.rule_processing_results,
                    
                    # Metadata
                    analysis_timestamp=result.analysis_timestamp,
                    processing_time_seconds=result.processing_time_seconds,
                    analysis_version=result.analysis_version
                )
                
                # Add back to active table
                db.add(analysis)
                
                # Remove from archive table
                db.execute(text("""
                    DELETE FROM fraud_analyses_archive 
                    WHERE order_name = :order_name
                """), {"order_name": order_name})
                
                print(f"  ✅ Unarchived successfully")
            else:
                print(f"\n  ❌ {order_name} not found in archive")
        
        # Commit all changes
        db.commit()
        print("\n✅ All unarchive operations completed successfully!")
        
        # Show current status
        active_count = db.query(FraudAnalysis).filter(
            FraudAnalysis.order_name.in_(orders_to_unarchive)
        ).count()
        
        archived_count = db.execute(text("""
            SELECT COUNT(*) FROM fraud_analyses_archive 
            WHERE order_name IN :orders
        """), {"orders": tuple(orders_to_unarchive)}).scalar()
        
        print(f"\nCurrent status:")
        print(f"  Active: {active_count}")
        print(f"  Archived: {archived_count}")
        
    except Exception as e:
        print(f"\n❌ Error during unarchive: {str(e)}")
        db.rollback()
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    unarchive_orders()