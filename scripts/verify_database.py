#!/usr/bin/env python3
"""
Verify database schema and delivery analytics functionality
"""
import sys
import os
sys.path.append('/Users/ruolez/Desktop/Dev/Shopify Automation/backend')

def verify_database():
    """Verify the database schema and column exists"""
    
    print("🔍 Verifying Database Schema")
    print("=" * 40)
    
    try:
        from sqlalchemy import create_engine, text
        from database import DATABASE_URL
        
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Check if delivery_analytics column exists
            result = conn.execute(text("""
                SELECT name, type 
                FROM pragma_table_info('fraud_analyses') 
                WHERE name='delivery_analytics'
            """))
            
            column_info = result.fetchone()
            
            if column_info:
                print("✅ delivery_analytics column exists")
                print(f"   Column name: {column_info[0]}")
                print(f"   Column type: {column_info[1]}")
            else:
                print("❌ delivery_analytics column does NOT exist")
                return False
            
            # Check all columns in fraud_analyses table
            print("\n📋 All columns in fraud_analyses table:")
            all_columns = conn.execute(text("SELECT name, type FROM pragma_table_info('fraud_analyses')"))
            
            for i, (name, col_type) in enumerate(all_columns.fetchall(), 1):
                marker = "🆕" if name == "delivery_analytics" else "  "
                print(f"   {i:2d}. {marker} {name} ({col_type})")
            
            # Check if there are any existing fraud analyses
            count_result = conn.execute(text("SELECT COUNT(*) FROM fraud_analyses"))
            total_analyses = count_result.scalar()
            
            print(f"\n📊 Total fraud analyses in database: {total_analyses}")
            
            if total_analyses > 0:
                # Check if any have delivery_analytics data
                analytics_result = conn.execute(text("""
                    SELECT COUNT(*) FROM fraud_analyses 
                    WHERE delivery_analytics IS NOT NULL
                """))
                with_analytics = analytics_result.scalar()
                
                print(f"   With delivery analytics: {with_analytics}")
                print(f"   Without delivery analytics: {total_analyses - with_analytics}")
            
            return True
            
    except Exception as e:
        print(f"❌ Database verification failed: {str(e)}")
        return False

def verify_models():
    """Verify the SQLAlchemy models can be loaded"""
    
    print("\n🔍 Verifying SQLAlchemy Models")
    print("=" * 40)
    
    try:
        from models import FraudAnalysis
        from sqlalchemy import inspect
        
        # Get the table columns
        inspector = inspect(FraudAnalysis)
        columns = inspector.columns
        
        print("✅ FraudAnalysis model loaded successfully")
        print(f"   Total columns: {len(columns)}")
        
        if 'delivery_analytics' in columns:
            print("✅ delivery_analytics column found in model")
            delivery_col = columns['delivery_analytics']
            print(f"   Column type: {delivery_col.type}")
        else:
            print("❌ delivery_analytics column NOT found in model")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Model verification failed: {str(e)}")
        return False

if __name__ == "__main__":
    print("🧪 Database and Model Verification Script")
    print("=" * 50)
    
    db_ok = verify_database()
    model_ok = verify_models()
    
    print(f"\n🎯 Verification Results:")
    print(f"   Database Schema: {'✅ OK' if db_ok else '❌ FAILED'}")
    print(f"   Model Loading: {'✅ OK' if model_ok else '❌ FAILED'}")
    
    if db_ok and model_ok:
        print(f"\n🎉 All verifications passed! Enhanced delivery tracking is ready.")
    else:
        print(f"\n⚠️  Some verifications failed. Check the errors above.")