#!/usr/bin/env python3
"""
Manually trigger fraud analysis for specific orders
"""

import sys
import os
import asyncio
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import ShopifyStore, FraudAnalysis
from enhanced_shopify_client import EnhancedShopifyClient
from fraud_service import FraudAnalysisService
from fraud_rule_processor import process_fraud_rules_for_order_async

async def analyze_order(order_name: str = "PW110547"):
    db = SessionLocal()
    try:
        # Get store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == "primewholesale-com.myshopify.com"
        ).first()
        
        if not store:
            print("Store not found!")
            return
            
        print(f"Analyzing order {order_name} for store {store.shop_name}")
        
        # Initialize enhanced client
        client = EnhancedShopifyClient(store.shop_domain, store.access_token)
        
        # Get order data
        print("Fetching order data...")
        order_data = await client.get_order_with_comprehensive_delivery_data(order_name)
        
        if not order_data:
            print("Order not found!")
            return
            
        print(f"Order found: {order_data.get('name', 'Unknown')}")
        print(f"Created at: {order_data.get('createdAt', 'Unknown')}")
        
        # Run fraud analysis
        print("\nRunning fraud analysis...")
        fraud_service = FraudAnalysisService(db)
        fraud_analysis = await fraud_service.analyze_order_fraud(
            order_data, 
            store, 
            db
        )
        
        if fraud_analysis:
            print(f"✅ Fraud analysis completed!")
            print(f"  - Risk level: {fraud_analysis.shopify_fraud_risk_level}")
            print(f"  - First time customer: {fraud_analysis.is_first_time_customer}")
            print(f"  - Duplicate order: {fraud_analysis.duplicate_within_7days}")
            print(f"  - Analysis ID: {fraud_analysis.id}")
            
            # Process fraud rules
            print("\nProcessing fraud detection rules...")
            result = await process_fraud_rules_for_order_async(
                order_data,
                store,
                db,
                fraud_analysis.id
            )
            
            if result:
                print(f"✅ Fraud rules processed!")
                print(f"  - Rules evaluated: {result.get('rules_evaluated', 0)}")
                print(f"  - Rules matched: {result.get('rules_matched', 0)}")
            else:
                print("❌ No fraud rules to process or error occurred")
        else:
            print("❌ Fraud analysis failed!")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    order_name = sys.argv[1] if len(sys.argv) > 1 else "PW110547"
    asyncio.run(analyze_order(order_name))