#!/usr/bin/env python3
"""
Initialize default admin user for the Shopify Automation Admin Panel.
Usage: python init_admin.py
"""

import os
import sys
from sqlalchemy.orm import Session

# Add the backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, create_tables
from models import AdminUser
from admin_auth import get_admin_password_hash

def create_default_admin(ensure_tables=True):
    """Create default admin user with credentials admin/admin"""
    
    # Only create tables if explicitly requested (e.g., when run directly)
    if ensure_tables:
        try:
            create_tables()
        except Exception as e:
            # Tables might already exist, which is fine
            pass
    
    db = SessionLocal()
    try:
        # Check if admin user already exists
        existing_admin = db.query(AdminUser).filter(AdminUser.username == "admin").first()
        if existing_admin:
            print("Admin user 'admin' already exists!")
            print(f"  Username: {existing_admin.username}")
            print(f"  Email: {existing_admin.email}")
            print(f"  Role: {existing_admin.role}")
            print(f"  Active: {existing_admin.is_active}")
            return
        
        # Password comes from env or is generated — never a fixed default
        admin_password = os.getenv("ADMIN_INITIAL_PASSWORD")
        generated = False
        if not admin_password:
            import secrets
            admin_password = secrets.token_urlsafe(12)
            generated = True

        admin_user = AdminUser(
            username="admin",
            email="admin@shopify-automation.local",
            full_name="System Administrator",
            hashed_password=get_admin_password_hash(admin_password),
            role="super_admin",
            is_active=True
        )

        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)

        print("✅ Default admin user created successfully!")
        print("")
        print("🔐 Admin Login Credentials:")
        print("  Username: admin")
        if generated:
            print(f"  Password: {admin_password}")
        else:
            print("  Password: (from ADMIN_INITIAL_PASSWORD)")
        print("")
        print("🌐 Admin Panel URL: http://localhost:3000/admin/login")
        print("")
        if generated:
            print("⚠️  IMPORTANT: This generated password is shown ONCE. Save it now,")
            print("   then change it after logging in (or set ADMIN_INITIAL_PASSWORD")
            print("   before first run to choose your own).")
        else:
            print("⚠️  IMPORTANT: Change the initial password after logging in!")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error creating admin user: {e}")
    finally:
        db.close()

def create_initial_admin():
    """Alias for create_default_admin for backward compatibility"""
    # When called from install script, tables are already created
    create_default_admin(ensure_tables=False)

if __name__ == "__main__":
    create_default_admin()