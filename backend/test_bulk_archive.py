#!/usr/bin/env python3
"""
Test script for bulk archive functionality.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import requests
from database import SessionLocal
from models import User, FraudAnalysis
from auth import create_access_token
from sqlalchemy import text

def test_bulk_archive():
    """Test the bulk archive functionality."""
    print("Testing bulk archive functionality...")
    
    # Get database session
    db = SessionLocal()
    
    try:
        # Get user with fraud analyses
        test_user = db.query(User).filter(User.id == 4).first()
        if not test_user:
            print("   ❌ Test user not found")
            return False
        
        token = create_access_token(data={"sub": test_user.email})
        headers = {"Authorization": f"Bearer {token}"}
        
        base_url = "http://localhost:8000"
        
        # Show current state
        print(f"\\n1. Current state:")
        active_count = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == test_user.id
        ).count()
        archived_count = db.execute(text(
            "SELECT COUNT(*) FROM fraud_analyses_archive WHERE user_id = :user_id"
        ), {"user_id": test_user.id}).scalar()
        
        print(f"   Active analyses: {active_count}")
        print(f"   Archived analyses: {archived_count}")
        
        # Test bulk archive endpoint
        print(f"\\n2. Testing bulk archive endpoint...")
        response = requests.post(
            f"{base_url}/fraud-detection/archive-fulfilled-cancelled",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Bulk archive successful:")
            print(f"   - Checked: {data['checked_count']} orders")
            print(f"   - Archived: {data['archived_count']} orders")
            if data['archived_orders']:
                print(f"   - Archived orders:")
                for order in data['archived_orders']:
                    print(f"     • {order['order_name']} ({order['archive_reason']})")
            print(f"   - Message: {data['message']}")
        else:
            print(f"   ❌ Bulk archive failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        # Show final state
        print(f"\\n3. Final state:")
        active_count_after = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == test_user.id
        ).count()
        archived_count_after = db.execute(text(
            "SELECT COUNT(*) FROM fraud_analyses_archive WHERE user_id = :user_id"
        ), {"user_id": test_user.id}).scalar()
        
        print(f"   Active analyses: {active_count_after}")
        print(f"   Archived analyses: {archived_count_after}")
        
        print("\\n✅ Bulk archive test completed!")
        return True
        
    except Exception as e:
        print(f"\\n❌ Error during testing: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = test_bulk_archive()
    sys.exit(0 if success else 1)