#!/usr/bin/env python3
"""
Test with order that has customer with unfulfilled previous orders
"""
import asyncio
import sys
import os

sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

from fraud_service import FraudAnalysisService
from shopify_client import ShopifyClient
from database import get_db
from models import ShopifyStore, User

async def test_no_fulfillment():
    """Test with order whose customer has previous orders with no fulfillment data"""
    
    db = next(get_db())
    store = db.query(ShopifyStore).filter(ShopifyStore.id == 2).first()
    user = db.query(User).filter(User.id == 4).first()
    
    fraud_service = FraudAnalysisService(db, store, user)
    client = ShopifyClient(
        shop_domain=store.shop_domain,
        access_token=store.access_token
    )
    
    # Test with PW110472 which had the customer with unfulfilled previous order PW15996
    order_name = "PW110472"
    print(f"Testing with order: {order_name}")
    
    order_data = await client.get_order_fraud_data(order_name)
    
    if order_data:
        # Test the _get_previous_order_data method
        prev_delivery_status, prev_order_total = fraud_service._get_previous_order_data(order_data)
        print(f"Previous delivery status: {prev_delivery_status}")
        print(f"Previous order total: {prev_order_total}")
        
        if prev_delivery_status is None:
            print("✅ Correctly returning None for orders without detailed delivery tracking")
        else:
            print(f"❌ Still returning basic status: {prev_delivery_status}")
    else:
        print("Order not found")

if __name__ == "__main__":
    asyncio.run(test_no_fulfillment())