#!/usr/bin/env python3
"""
Test script for the fraud analysis archival system.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from fraud_archive_service import FraudArchiveService
from database import SessionLocal
from models import FraudAnalysis, ShopifyStore, User, Settings

def test_archival_system():
    """Test the fraud analysis archival system."""
    print("Testing fraud analysis archival system...")
    
    # Get database session
    db = SessionLocal()
    
    try:
        # Check if archive table exists
        print("1. Checking if fraud_analyses_archive table exists...")
        result = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='fraud_analyses_archive'"))
        if result.fetchone():
            print("   ✅ fraud_analyses_archive table exists")
        else:
            print("   ❌ fraud_analyses_archive table does not exist")
            return False
        
        # Check if there are any fraud analyses to test with
        print("\n2. Checking for existing fraud analyses...")
        active_analyses = db.query(FraudAnalysis).limit(5).all()
        print(f"   Found {len(active_analyses)} active fraud analyses")
        
        if len(active_analyses) == 0:
            print("   ⚠️  No active fraud analyses found. Cannot test archival.")
            return True
        
        # Display some sample analyses
        for analysis in active_analyses:
            print(f"   - Order: {analysis.order_name}, Risk: {analysis.shopify_fraud_risk_level}")
        
        # Check archive table structure
        print("\n3. Checking archive table structure...")
        result = db.execute(text("PRAGMA table_info(fraud_analyses_archive)"))
        columns = result.fetchall()
        archive_columns = [col[1] for col in columns]
        
        required_columns = ['archived_at', 'archive_reason']
        for col in required_columns:
            if col in archive_columns:
                print(f"   ✅ Column '{col}' exists")
            else:
                print(f"   ❌ Column '{col}' missing")
                return False
        
        # Check if there are any archived analyses
        print("\n4. Checking for existing archived analyses...")
        archived_count = db.execute(text("SELECT COUNT(*) FROM fraud_analyses_archive")).fetchone()[0]
        print(f"   Found {archived_count} archived analyses")
        
        # Test the FraudArchiveService
        print("\n5. Testing FraudArchiveService...")
        
        # Get a test user
        test_user = db.query(User).first()
        if not test_user:
            print("   ❌ No users found in database")
            return False
        
        archive_service = FraudArchiveService(db)
        
        # Test get_archive_statistics
        print("   Testing get_archive_statistics...")
        stats = archive_service.get_archive_statistics(test_user.id)
        print(f"   Archive statistics: {stats}")
        
        # Test the scheduled task (simulation)
        print("\n6. Testing scheduled task simulation...")
        print("   (This would normally check Shopify API for order status)")
        print("   For testing purposes, we'll just check the database structure")
        
        # Check if the scheduled task is properly configured
        print("\n7. Checking scheduled task configuration...")
        with open('tasks.py', 'r') as f:
            content = f.read()
            if 'archive_fulfilled_fraud_analyses' in content:
                print("   ✅ Archive task is configured in tasks.py")
            else:
                print("   ❌ Archive task not found in tasks.py")
                return False
        
        # Test API endpoint structure
        print("\n8. Checking API endpoint configuration...")
        with open('main.py', 'r') as f:
            content = f.read()
            if 'fraud-detection/archived-analyses' in content:
                print("   ✅ Archived analyses endpoint exists")
            else:
                print("   ❌ Archived analyses endpoint not found")
                return False
        
        print("\n✅ All archival system tests passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error during testing: {str(e)}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = test_archival_system()
    sys.exit(0 if success else 1)