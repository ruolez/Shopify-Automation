#!/usr/bin/env python3
"""Manually run fraud analysis on TS8305843"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import User, ShopifyStore
from fraud_service import FraudAnalysisService
from shopify_client import ShopifyClient
import logging

# Set up logging to see all debug output
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

db = SessionLocal()
try:
    # Get user and store
    user = db.query(User).filter(User.email == "alexr@tobaccogeneral.com").first()
    if not user:
        print("User not found")
        exit(1)
    
    store = db.query(ShopifyStore).filter(ShopifyStore.user_id == user.id).first()
    if not store:
        print("Store not found")
        exit(1)
    
    print(f"Using store: {store.store_name}")
    
    # Create services
    shopify_client = ShopifyClient(store.shop_domain, store.access_token)
    fraud_service = FraudAnalysisService(db, user, store)
    
    # Analyze the specific order
    print("\n=== Analyzing order TS8305843 ===")
    result = fraud_service.analyze_order("TS8305843")
    
    if result['success']:
        print("\nAnalysis succeeded!")
        analysis = result['analysis']
        print(f"Age Checker Detected: {analysis.age_checker_detected}")
        print(f"Customer Notes: {analysis.customer_notes}")
        print(f"Additional Details: {analysis.additional_details}")
    else:
        print(f"\nAnalysis failed: {result['error']}")
        
finally:
    db.close()