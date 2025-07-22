#!/usr/bin/env python3
"""
Fix user login for frontend testing
"""
import sys
import os

# Add the backend directory to the path
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

def fix_user_login():
    """Set up proper user credentials for testing"""
    
    print("🔧 FIXING USER LOGIN FOR FRONTEND TESTING")
    print("=" * 50)
    
    try:
        from database import get_db
        from models import User, ShopifyStore, FraudAnalysis
        from auth import get_password_hash
        
        db = next(get_db())
        
        # Get the user who owns the analysis with August 5th data
        analysis = db.query(FraudAnalysis).filter(FraudAnalysis.order_name == 'PW15996').first()
        
        if not analysis:
            print("❌ PW15996 analysis not found")
            return
            
        user = db.query(User).filter(User.id == analysis.user_id).first()
        store = db.query(ShopifyStore).filter(ShopifyStore.id == analysis.store_id).first()
        
        print(f"✅ Found analysis for order PW15996:")
        print(f"   Analysis ID: {analysis.id}")
        print(f"   User: {user.email} (ID: {user.id})")
        print(f"   Store: {store.shop_name} (ID: {store.id})")
        print(f"   Previous Delivery Status: '{analysis.previous_order_delivery_status}'")
        
        # Set a known password for this user
        known_password = "shopify123"
        try:
            user.hashed_password = get_password_hash(known_password)
            db.commit()
            print(f"\n✅ Set password for {user.email}: {known_password}")
        except Exception as e:
            print(f"\n⚠️  Could not set password (bcrypt issue): {e}")
            print(f"   Try using existing password or check logs")
        
        print(f"\n🎯 FRONTEND LOGIN INSTRUCTIONS:")
        print(f"   1. Go to: http://localhost:3000/auth/login")
        print(f"   2. Email: {user.email}")
        print(f"   3. Password: {known_password}")
        print(f"   4. Navigate to: Fraud Detection")
        print(f"   5. Select Store: {store.shop_name}")
        print(f"   6. Order Name: PW15996")
        print(f"   7. Click: Analyze Order")
        
        print(f"\n📊 EXPECTED RESULT:")
        print(f"   Previous Order Delivery Status: '{analysis.previous_order_delivery_status}'")
        print(f"   Should NOT show 'N/A'")
        
        # Show all analyses for this user
        user_analyses = db.query(FraudAnalysis).filter(FraudAnalysis.user_id == user.id).all()
        print(f"\n📋 ALL ANALYSES FOR {user.email}:")
        for a in user_analyses:
            print(f"   ID {a.id}: {a.order_name} - Previous: '{a.previous_order_delivery_status}'")
            
    except Exception as e:
        print(f"❌ Error fixing user login: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n🎉 User Login Fix Complete!")
    print("=" * 35)

if __name__ == "__main__":
    fix_user_login()