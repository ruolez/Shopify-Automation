#!/usr/bin/env python3
"""
Test the reconcile API endpoint directly inside the container
"""
import sys
sys.path.insert(0, '/app')

import asyncio
from database import SessionLocal
from models import User, Settings
from fraud_archive_service import FraudArchiveService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_reconcile():
    """Test the reconcile process"""
    db = SessionLocal()
    try:
        # Get the first user with fraud sync enabled
        user = db.query(User).join(Settings).filter(
            Settings.fraud_sync_enabled == True
        ).first()
        
        if not user:
            logger.error("No users with fraud sync enabled")
            return False
        
        logger.info(f"Testing reconcile for user: {user.email}")
        
        # Create archive service
        archive_service = FraudArchiveService(db)
        
        # Run reconcile with a small batch
        result = await archive_service.archive_fulfilled_and_cancelled_analyses(
            user.id,
            max_analyses=5  # Process only 5 for testing
        )
        
        logger.info(f"Result: {result}")
        
        if result["archived"] > 0:
            logger.info(f"✓ Successfully archived {result['archived']} analyses")
        elif result["checked"] > 0:
            logger.info(f"✓ Checked {result['checked']} analyses, none needed archiving")
        else:
            logger.info("No analyses to process")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during reconcile: {str(e)}", exc_info=True)
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        success = loop.run_until_complete(test_reconcile())
        if success:
            print("\n✓ Reconcile test completed successfully")
        else:
            print("\n✗ Reconcile test failed")
    finally:
        loop.close()