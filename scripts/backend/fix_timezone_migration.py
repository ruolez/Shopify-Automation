#!/usr/bin/env python3
"""
One-time migration script to fix timezone-naive datetime values in the database.
Converts all naive datetimes to UTC-aware datetimes.
"""
import sys
from datetime import timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from database import DATABASE_URL
from models import ShopifyStore, ProcessedOrder, OrderLog, OutOfStockIncident, FraudAnalysis, AdminAuditLog

def fix_timezone_naive_datetimes():
    """Convert all timezone-naive datetimes to UTC-aware datetimes."""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Fix ShopifyStore.last_sync
        print("Fixing timezone-naive datetimes in ShopifyStore.last_sync...")
        stores = session.query(ShopifyStore).all()
        fixed_count = 0
        
        for store in stores:
            if store.last_sync and store.last_sync.tzinfo is None:
                store.last_sync = store.last_sync.replace(tzinfo=timezone.utc)
                fixed_count += 1
        
        session.commit()
        print(f"Fixed {fixed_count} ShopifyStore records")
        
        # Fix ProcessedOrder.processed_at
        print("\nFixing timezone-naive datetimes in ProcessedOrder.processed_at...")
        processed_orders = session.query(ProcessedOrder).all()
        fixed_count = 0
        
        for order in processed_orders:
            if order.processed_at and order.processed_at.tzinfo is None:
                order.processed_at = order.processed_at.replace(tzinfo=timezone.utc)
                fixed_count += 1
        
        session.commit()
        print(f"Fixed {fixed_count} ProcessedOrder records")
        
        # Fix OrderLog timestamps
        print("\nFixing timezone-naive datetimes in OrderLog...")
        logs = session.query(OrderLog).all()
        fixed_count = 0
        
        for log in logs:
            modified = False
            if log.created_at and log.created_at.tzinfo is None:
                log.created_at = log.created_at.replace(tzinfo=timezone.utc)
                modified = True
            if hasattr(log, 'processed_at') and log.processed_at and log.processed_at.tzinfo is None:
                log.processed_at = log.processed_at.replace(tzinfo=timezone.utc)
                modified = True
            if modified:
                fixed_count += 1
        
        session.commit()
        print(f"Fixed {fixed_count} OrderLog records")
        
        # Fix OutOfStockIncident timestamps
        print("\nFixing timezone-naive datetimes in OutOfStockIncident...")
        incidents = session.query(OutOfStockIncident).all()
        fixed_count = 0
        
        for incident in incidents:
            if incident.created_at and incident.created_at.tzinfo is None:
                incident.created_at = incident.created_at.replace(tzinfo=timezone.utc)
                fixed_count += 1
        
        session.commit()
        print(f"Fixed {fixed_count} OutOfStockIncident records")
        
        # Fix FraudAnalysis timestamps
        print("\nFixing timezone-naive datetimes in FraudAnalysis...")
        analyses = session.query(FraudAnalysis).all()
        fixed_count = 0
        
        for analysis in analyses:
            modified = False
            if analysis.analysis_timestamp and analysis.analysis_timestamp.tzinfo is None:
                analysis.analysis_timestamp = analysis.analysis_timestamp.replace(tzinfo=timezone.utc)
                modified = True
            if analysis.order_created_at and analysis.order_created_at.tzinfo is None:
                analysis.order_created_at = analysis.order_created_at.replace(tzinfo=timezone.utc)
                modified = True
            if modified:
                fixed_count += 1
        
        session.commit()
        print(f"Fixed {fixed_count} FraudAnalysis records")
        
        # Fix AdminAuditLog timestamps
        print("\nFixing timezone-naive datetimes in AdminAuditLog...")
        audit_logs = session.query(AdminAuditLog).all()
        fixed_count = 0
        
        for audit_log in audit_logs:
            if audit_log.created_at and audit_log.created_at.tzinfo is None:
                audit_log.created_at = audit_log.created_at.replace(tzinfo=timezone.utc)
                fixed_count += 1
        
        session.commit()
        print(f"Fixed {fixed_count} AdminAuditLog records")
        
        print("\n✅ Migration completed successfully!")
        
    except Exception as e:
        session.rollback()
        print(f"\n❌ Error during migration: {e}")
        sys.exit(1)
    finally:
        session.close()

if __name__ == "__main__":
    print("Starting timezone migration...")
    print("This will convert all timezone-naive datetimes to UTC-aware datetimes.")
    print("Make sure to backup your database before proceeding!\n")
    
    response = input("Do you want to continue? (yes/no): ")
    if response.lower() != 'yes':
        print("Migration cancelled.")
        sys.exit(0)
    
    fix_timezone_naive_datetimes()