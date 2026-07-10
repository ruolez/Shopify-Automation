#!/usr/bin/env python3
"""
Create test data for admin user to demonstrate dashboard functionality
"""

import os
import sys
from datetime import datetime, timedelta, timezone
import json
import random

# Add the backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import User, ShopifyStore, ProcessingRule, OrderLog, ProcessedOrder

def create_test_data_for_admin():
    """Create test data for admin user (ID 2)"""
    
    db = SessionLocal()
    
    try:
        # Get admin user
        admin_user = db.query(User).filter(User.id == 2).first()
        if not admin_user:
            print("❌ Admin user (ID 2) not found!")
            return
        
        print(f"Creating test data for: {admin_user.email}")
        
        # Create a test store for admin
        test_store = db.query(ShopifyStore).filter(
            ShopifyStore.user_id == 2,
            ShopifyStore.shop_name == "Demo Store"
        ).first()
        
        if not test_store:
            test_store = ShopifyStore(
                user_id=2,
                shop_name="Demo Store",
                shop_domain="demo-store.myshopify.com",
                access_token="shpat_demo_token_12345",
                is_active=True,
                created_at=datetime.now(timezone.utc) - timedelta(days=30),
                last_sync=datetime.now(timezone.utc) - timedelta(hours=2)
            )
            db.add(test_store)
            db.commit()
            db.refresh(test_store)
            print("✅ Created Demo Store")
        else:
            print("✓ Demo Store already exists")
        
        # Create a test rule for admin
        test_rule = db.query(ProcessingRule).filter(
            ProcessingRule.user_id == 2,
            ProcessingRule.name == "Demo Rule - Priority Orders"
        ).first()
        
        if not test_rule:
            test_rule = ProcessingRule(
                user_id=2,
                name="Demo Rule - Priority Orders",
                store_id=test_store.id,
                conditions=json.dumps({
                    "weight": {"operator": "greater_than", "value": 10},
                    "shipping_country": {"operator": "equals", "value": "US"}
                }),
                actions=json.dumps({
                    "add_tags": ["priority", "heavy"],
                    "change_location": "warehouse-1"
                }),
                priority=1,
                is_active=True,
                created_at=datetime.now(timezone.utc) - timedelta(days=20)
            )
            db.add(test_rule)
            db.commit()
            db.refresh(test_rule)
            print("✅ Created Demo Rule")
        else:
            print("✓ Demo Rule already exists")
        
        # Check if we already have order logs
        existing_logs = db.query(OrderLog).filter(OrderLog.user_id == 2).count()
        if existing_logs > 0:
            print(f"✓ Already have {existing_logs} order logs for admin")
        else:
            # Create sample order logs for the last 7 days
            order_logs = []
            processed_orders = []
            
            # Generate data for last 7 days
            for days_ago in range(7):
                date = datetime.now(timezone.utc) - timedelta(days=days_ago)
                
                # Random number of orders per day (5-20)
                num_orders = random.randint(5, 20)
                
                for i in range(num_orders):
                    order_num = f"DEMO-{1000 + (days_ago * 100) + i}"
                    order_id = f"gid://shopify/Order/{5000000 + (days_ago * 100) + i}"
                    
                    # Success rate of ~90%
                    is_success = random.random() < 0.9
                    
                    # Create processed order record
                    processed_order = ProcessedOrder(
                        order_id=order_id,
                        order_number=order_num,
                        store_id=test_store.id,
                        processed_at=date - timedelta(hours=random.randint(0, 23)),
                        rules_applied=json.dumps(["Demo Rule - Priority Orders"] if random.random() < 0.6 else [])
                    )
                    processed_orders.append(processed_order)
                    
                    # Create order log
                    order_log = OrderLog(
                        user_id=2,
                        store_id=test_store.id,
                        order_id=order_id,
                        order_number=order_num,
                        action="rule_applied" if is_success and random.random() < 0.6 else "order_processed",
                        status="success" if is_success else "error",
                        details=json.dumps({
                            "rule_name": "Demo Rule - Priority Orders",
                            "tags_added": ["priority", "heavy"],
                            "location_changed": "warehouse-1"
                        }) if is_success and random.random() < 0.6 else None,
                        error_message=None if is_success else "Failed to update order: API rate limit exceeded",
                        created_at=date - timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                    )
                    order_logs.append(order_log)
            
            # Bulk insert
            db.bulk_save_objects(processed_orders)
            db.bulk_save_objects(order_logs)
            db.commit()
            
            print(f"✅ Created {len(order_logs)} order logs")
            print(f"✅ Created {len(processed_orders)} processed orders")
        
        # Create some recent activity (last hour)
        recent_logs = []
        for i in range(5):
            order_num = f"DEMO-RECENT-{1000 + i}"
            order_id = f"gid://shopify/Order/{6000000 + i}"
            
            recent_log = OrderLog(
                user_id=2,
                store_id=test_store.id,
                order_id=order_id,
                order_number=order_num,
                action="order_processed",
                status="success",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=random.randint(5, 55))
            )
            recent_logs.append(recent_log)
        
        if recent_logs:
            db.bulk_save_objects(recent_logs)
            db.commit()
            print(f"✅ Created {len(recent_logs)} recent order logs")
        
        # Summary
        total_logs = db.query(OrderLog).filter(OrderLog.user_id == 2).count()
        total_orders = db.query(ProcessedOrder).join(ShopifyStore).filter(ShopifyStore.user_id == 2).count()
        
        print("\n📊 Test Data Summary for Admin User:")
        print(f"  - Stores: 1 (Demo Store)")
        print(f"  - Rules: 1 (Demo Rule - Priority Orders)")
        print(f"  - Order Logs: {total_logs}")
        print(f"  - Processed Orders: {total_orders}")
        print("\n✅ Test data creation complete!")
        print("You should now see data in the dashboard when logged in as admin@example.com")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error creating test data: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    create_test_data_for_admin()