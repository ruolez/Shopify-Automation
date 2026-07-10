#!/usr/bin/env python3
"""Enhanced fraud service with detailed logging for duplicate detection debugging"""

import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from models import FraudAnalysis, ShopifyStore, User, Settings
from fraud_service import FraudAnalysisService

logger = logging.getLogger(__name__)

class EnhancedFraudAnalysisService(FraudAnalysisService):
    """Enhanced fraud service with detailed duplicate detection logging"""
    
    def _check_duplicate_within_configurable_days(self, order_data: Dict[str, Any]) -> bool:
        """Enhanced version with detailed logging"""
        logger.info("\n=== ENHANCED DUPLICATE DETECTION START ===")
        try:
            # Log order data structure
            logger.info(f"Order data keys: {list(order_data.keys())[:10]}")
            
            customer = order_data.get('customer', {})
            if not customer:
                logger.warning("No customer data found - returning False")
                return False
            
            logger.info(f"Customer data found with keys: {list(customer.keys())[:10]}")
            
            # Get user's configured duplicate detection period
            logger.info(f"Checking settings for user_id: {self.user.id}")
            user_settings = self.db.query(Settings).filter(Settings.user_id == self.user.id).first()
            
            if user_settings:
                logger.info(f"User settings found:")
                logger.info(f"  - duplicate_detection_days: {user_settings.duplicate_detection_days}")
                logger.info(f"  - auto_sync_enabled: {user_settings.auto_sync_enabled}")
                logger.info(f"  - sync_frequency_minutes: {user_settings.sync_frequency_minutes}")
                duplicate_detection_days = user_settings.duplicate_detection_days
            else:
                logger.warning("No user settings found - using default 7 days")
                duplicate_detection_days = 7
            
            logger.info(f"Using duplicate_detection_days: {duplicate_detection_days}")
            
            # Get order creation date - handle both data formats
            if 'order_info' in order_data:
                # Manual analysis format (nested)
                logger.info("Using nested order_info format")
                order_info = order_data.get('order_info', {})
                created_at_str = order_info.get('created_at', '')
                current_order_id = order_info.get('id', '')
                current_order_name = order_info.get('name', '')
            else:
                # Bulk analysis format (direct GraphQL)
                logger.info("Using direct GraphQL format")
                created_at_str = order_data.get('createdAt', '')
                current_order_id = order_data.get('id', '')
                current_order_name = order_data.get('name', '')
                
            logger.info(f"Current order: {current_order_name} (ID: {current_order_id})")
            logger.info(f"Created at string: {created_at_str}")
            
            if not created_at_str:
                logger.error("No creation date for current order - returning False")
                return False
            
            created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            detection_period_ago = created_at - timedelta(days=duplicate_detection_days)
            
            logger.info(f"Current order created at: {created_at}")
            logger.info(f"Detection period starts: {detection_period_ago}")
            logger.info(f"Window: {duplicate_detection_days} days")
            
            # Check customer's order history for orders within configured days
            customer_orders = customer.get('orders', {}).get('edges', [])
            logger.info(f"Customer has {len(customer_orders)} total orders in history")
            
            duplicate_count = 0
            duplicate_orders_found = []
            
            for i, order_edge in enumerate(customer_orders):
                order = order_edge['node']
                order_name = order.get('name', 'Unknown')
                order_created_str = order.get('createdAt', '')
                order_id = order.get('id', '')
                
                logger.debug(f"  Checking order {i+1}: {order_name} (ID: {order_id})")
                
                if order_created_str and order.get('id') != current_order_id:
                    order_created = datetime.fromisoformat(order_created_str.replace('Z', '+00:00'))
                    days_diff = (created_at - order_created).total_seconds() / 86400  # Convert to days
                    
                    logger.debug(f"    Created: {order_created} ({days_diff:.1f} days before current)")
                    
                    if detection_period_ago <= order_created <= created_at:
                        duplicate_count += 1
                        duplicate_orders_found.append({
                            'name': order_name,
                            'created': order_created,
                            'days_before': days_diff
                        })
                        logger.info(f"    ✓ DUPLICATE FOUND: {order_name} ({days_diff:.1f} days before)")
                    else:
                        logger.debug(f"    ✗ Outside window")
                else:
                    if order.get('id') == current_order_id:
                        logger.debug(f"    - Skipping (same as current order)")
                    else:
                        logger.debug(f"    - Skipping (no creation date)")
            
            result = duplicate_count > 0
            logger.info(f"\n=== DUPLICATE DETECTION RESULT ===")
            logger.info(f"Duplicate orders found: {duplicate_count}")
            logger.info(f"Duplicate orders: {duplicate_orders_found}")
            logger.info(f"Returning: {result}")
            logger.info("=== DUPLICATE DETECTION END ===\n")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in enhanced duplicate detection: {str(e)}", exc_info=True)
            return False

async def test_enhanced_duplicate_detection(user_id: int, store_id: int, order_name: str):
    """Test the enhanced duplicate detection"""
    from database import SessionLocal
    from shopify_client import ShopifyClient
    
    db = SessionLocal()
    try:
        # Get user and store
        user = db.query(User).filter(User.id == user_id).first()
        store = db.query(ShopifyStore).filter(ShopifyStore.id == store_id).first()
        
        if not user or not store:
            logger.error("User or store not found")
            return
        
        # Get fraud analysis
        analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.order_name == order_name
        ).first()
        
        if not analysis:
            logger.error(f"No fraud analysis found for order {order_name}")
            return
        
        logger.info(f"\n=== Testing Enhanced Duplicate Detection ===")
        logger.info(f"Order: {order_name}")
        logger.info(f"Current duplicate_within_7days: {analysis.duplicate_within_7days}")
        
        # Get order data
        client = ShopifyClient(store.shop_domain, store.access_token)
        order_id = analysis.shopify_order_id
        if not order_id.startswith('gid://'):
            order_id = f"gid://shopify/Order/{order_id}"
        
        order_data = await client.get_order_by_id(order_id)
        
        if not order_data:
            logger.error("Could not fetch order data")
            return
        
        # Test with enhanced service
        enhanced_service = EnhancedFraudAnalysisService(db, store, user)
        result = enhanced_service._check_duplicate_within_configurable_days(order_data)
        
        logger.info(f"\nEnhanced service result: {result}")
        logger.info(f"Matches stored value? {result == analysis.duplicate_within_7days}")
        
        # Try updating if different
        if result != analysis.duplicate_within_7days:
            logger.info("\nAttempting to update stored value...")
            analysis.duplicate_within_7days = result
            db.commit()
            logger.info("✓ Update committed")
            
            # Verify
            db.refresh(analysis)
            logger.info(f"Verification: New value = {analysis.duplicate_within_7days}")
        
    except Exception as e:
        logger.error(f"Test failed: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    import asyncio
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) != 4:
        print("Usage: python debug_fraud_service_enhanced.py <user_id> <store_id> <order_name>")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    store_id = int(sys.argv[2])
    order_name = sys.argv[3]
    
    asyncio.run(test_enhanced_duplicate_detection(user_id, store_id, order_name))