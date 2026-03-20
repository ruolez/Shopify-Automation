"""
Migration script to encrypt existing plaintext Shopify access tokens.

This script should be run once after deploying the encryption feature.
It will encrypt all existing plaintext tokens in the database.

Usage:
    1. Ensure ENCRYPTION_KEY is set in your environment
    2. Run: python migrations/encrypt_existing_tokens.py

WARNING:
    - Make a database backup before running this migration
    - This is a one-way operation - tokens cannot be decrypted without the key
"""

import os
import sys

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from encryption import encrypt_token, is_token_encrypted, ENCRYPTED_PREFIX


def migrate_tokens():
    """Encrypt all plaintext access tokens in the database."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is not set")
        sys.exit(1)

    encryption_key = os.environ.get("ENCRYPTION_KEY")
    if not encryption_key:
        print("ERROR: ENCRYPTION_KEY environment variable is not set")
        print("Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
        sys.exit(1)

    print("Connecting to database...")
    engine = create_engine(database_url)

    with engine.connect() as conn:
        # Get all stores with plaintext tokens
        result = conn.execute(text("SELECT id, shop_domain, access_token FROM shopify_stores"))
        stores = result.fetchall()

        if not stores:
            print("No stores found in database.")
            return

        print(f"Found {len(stores)} stores to check.")
        encrypted_count = 0
        already_encrypted_count = 0
        error_count = 0

        for store in stores:
            store_id, shop_domain, access_token = store

            if not access_token:
                print(f"  - Store {store_id} ({shop_domain}): No token, skipping")
                continue

            if is_token_encrypted(access_token):
                print(f"  - Store {store_id} ({shop_domain}): Already encrypted, skipping")
                already_encrypted_count += 1
                continue

            try:
                encrypted_token = encrypt_token(access_token)
                conn.execute(
                    text("UPDATE shopify_stores SET access_token = :token WHERE id = :id"),
                    {"token": encrypted_token, "id": store_id}
                )
                print(f"  - Store {store_id} ({shop_domain}): Token encrypted successfully")
                encrypted_count += 1
            except Exception as e:
                print(f"  - Store {store_id} ({shop_domain}): ERROR - {str(e)}")
                error_count += 1

        conn.commit()

        print("\n" + "=" * 50)
        print("Migration Summary:")
        print(f"  Total stores:       {len(stores)}")
        print(f"  Newly encrypted:    {encrypted_count}")
        print(f"  Already encrypted:  {already_encrypted_count}")
        print(f"  Errors:             {error_count}")
        print("=" * 50)

        if error_count > 0:
            print("\nWARNING: Some tokens failed to encrypt. Please review the errors above.")
            sys.exit(1)


if __name__ == "__main__":
    print("=" * 50)
    print("Shopify Access Token Encryption Migration")
    print("=" * 50)
    print()

    # Check if running in CI/automated environment
    if os.environ.get("CI") or os.environ.get("AUTOMATED"):
        print("Running in automated mode...")
        migrate_tokens()
    else:
        print("This script will encrypt all plaintext Shopify access tokens.")
        print("Make sure you have backed up your database before proceeding.")
        print()
        response = input("Do you want to continue? (yes/no): ")
        if response.lower() == "yes":
            migrate_tokens()
        else:
            print("Migration cancelled.")
            sys.exit(0)
