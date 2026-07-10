#!/usr/bin/env python3
"""
Check fraud detection status for stores and recent orders
"""

import sys
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import engine
from models import User, ShopifyStore, Settings, FraudAnalysis, OrderLog
from sqlalchemy import desc

# Create session
Session = sessionmaker(bind=engine)
db = Session()

try:
    # Get all users with their settings
    users = db.query(User).all()
    
    for user in users:
        print(f"\n{'='*60}")
        print(f"User: {user.email} (ID: {user.id})")
        
        # Get user settings
        settings = db.query(Settings).filter(Settings.user_id == user.id).first()
        if settings:
            print(f"  Auto Sync: {settings.auto_sync_enabled}")
            print(f"  Fraud Sync: {settings.fraud_sync_enabled}")
            print(f"  Sync Window: {settings.sync_window_days} days")
            print(f"  Duplicate Detection: {settings.duplicate_detection_days} days")
        else:
            print("  No settings found")
        
        # Get stores
        stores = db.query(ShopifyStore).filter(
            ShopifyStore.user_id == user.id
        ).all()
        
        for store in stores:
            print(f"\n  Store: {store.shop_name} ({store.shop_domain})")
            print(f"    Active: {store.is_active}")
            print(f"    Last Sync: {store.last_sync}")
            
            # Count fraud analyses
            fraud_count = db.query(FraudAnalysis).filter(
                FraudAnalysis.store_id == store.id
            ).count()
            print(f"    Total Fraud Analyses: {fraud_count}")
            
            # Get recent fraud analyses
            recent_frauds = db.query(FraudAnalysis).filter(
                FraudAnalysis.store_id == store.id
            ).order_by(desc(FraudAnalysis.analysis_timestamp)).limit(5).all()
            
            if recent_frauds:
                print(f"    Recent Fraud Analyses:")
                for fraud in recent_frauds:
                    print(f"      - Order {fraud.order_name}: {fraud.shopify_fraud_risk_level} risk, Analyzed: {fraud.analysis_timestamp}")
            
            # Get most recent order logs
            recent_logs = db.query(OrderLog).filter(
                OrderLog.store_id == store.id
            ).order_by(desc(OrderLog.created_at)).limit(5).all()
            
            if recent_logs:
                print(f"    Recent Order Logs:")
                for log in recent_logs:
                    print(f"      - Order {log.order_number}: {log.action} ({log.status}) at {log.created_at}")
    
    print(f"\n{'='*60}")
    
    # Check for any recent fraud analyses across all stores
    recent_window = datetime.now(timezone.utc) - timedelta(minutes=10)
    recent_fraud_count = db.query(FraudAnalysis).filter(
        FraudAnalysis.analysis_timestamp >= recent_window
    ).count()
    
    print(f"\nFraud analyses created in last 10 minutes: {recent_fraud_count}")
    
except Exception as e:
    print(f"Error: {e}")
    raise
finally:
    db.close()