"""
Migration: Add fraud_sync_days column to settings table
"""
import sys
sys.path.append('/app')
from sqlalchemy import text
from database import get_db

def migrate_add_fraud_sync_days():
    """Add fraud_sync_days column to settings table"""
    db = next(get_db())
    try:
        # Check if column already exists
        result = db.execute(text("PRAGMA table_info(settings)"))
        columns = [row[1] for row in result]
        
        if 'fraud_sync_days' in columns:
            print("✅ fraud_sync_days column already exists")
            return True
        
        # Add the column
        print("🔄 Adding fraud_sync_days column to settings table...")
        db.execute(text("""
            ALTER TABLE settings 
            ADD COLUMN fraud_sync_days INTEGER DEFAULT 7
        """))
        db.commit()
        
        print("✅ Successfully added fraud_sync_days column")
        
        # Verify the column was added
        result = db.execute(text("PRAGMA table_info(settings)"))
        columns = [row[1] for row in result]
        
        if 'fraud_sync_days' in columns:
            print("✅ Verified: fraud_sync_days column exists")
            return True
        else:
            print("❌ Error: fraud_sync_days column was not added")
            return False
            
    except Exception as e:
        print(f"❌ Error adding fraud_sync_days column: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = migrate_add_fraud_sync_days()
    exit(0 if success else 1)