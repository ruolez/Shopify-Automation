from celery import Celery
from celery.schedules import crontab
import os
import sys
import asyncio
import logging
import pytz
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

# Add the app directory to Python path
sys.path.insert(0, '/app')

from database import SessionLocal, engine
from models import User, ShopifyStore, ProcessingRule, OrderLog, TaskStatus, Settings, ProcessedOrder, LocationAlias, LocationMapping, OutOfStockIncident, ExcludedSKU, FraudAnalysis, ProcessedFraudOrder
from shopify_client import ShopifyClient
from enhanced_shopify_client import EnhancedShopifyClient
from rule_engine import RuleEngine
from fraud_service import FraudAnalysisService
from fraud_rule_processor import process_fraud_rules_for_order_async
from fraud_archive_service import FraudArchiveService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Celery
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery = Celery("shopify_automation", broker=redis_url, backend=redis_url)

# Celery configuration
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

# Schedule periodic tasks - Dynamic scheduling based on user settings
celery.conf.beat_schedule = {
    'process-all-orders': {
        'task': 'tasks.process_all_orders_if_enabled',
        'schedule': crontab(minute='*'),  # Check every minute if sync should run
    },
    'process-fraud-detection': {
        'task': 'tasks.process_fraud_detection_if_enabled',
        'schedule': crontab(minute='*'),  # Check every minute if fraud detection should run
    },
    'cleanup-old-logs': {
        'task': 'tasks.cleanup_old_logs',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },
    'archive-fraud-analyses': {
        'task': 'tasks.archive_fulfilled_fraud_analyses',
        'schedule': crontab(minute=0),  # Every hour
    },
}

def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

def _combine_product_and_variant_title(product_title: str, variant_title: str) -> str:
    """Combine product title and variant title for display"""
    if not product_title:
        product_title = "Unknown Product"
    
    if variant_title and variant_title.strip():
        return f"{product_title} {variant_title}"
    
    return product_title

def _record_oos_incident(
    db: Session,
    user_id: int,
    store_id: int, 
    order: Dict,
    rule_name: str,
    attempted_location_id: str,
    attempted_location_alias: str = None,
    excluded_skus: List[str] = None
):
    """Record out-of-stock incidents for all products in an order"""
    try:
        order_id = order["id"]
        order_number = order.get("name", "Unknown")
        incident_date = datetime.now(timezone.utc)
        
        # Get line items from the order
        line_items = order.get("lineItems", {}).get("edges", [])
        excluded_skus = excluded_skus or []
        
        for item_edge in line_items:
            item = item_edge["node"]
            product = item.get("product", {})
            variant = item.get("variant", {})
            
            # Extract product information
            product_id = product.get("id", "")
            variant_id = variant.get("id", "")
            base_product_title = item.get("title", "Unknown Product")
            variant_title = variant.get("title", "")
            # Filter out "Default Title" - store as empty string instead
            if variant_title == "Default Title":
                variant_title = ""
            combined_product_title = _combine_product_and_variant_title(base_product_title, variant_title)
            sku = variant.get("sku", "")
            
            # Skip excluded SKUs
            if sku and excluded_skus:
                skip_item = False
                for excluded_pattern in excluded_skus:
                    if excluded_pattern.lower() in sku.lower():
                        logger.info(f"✅ EXCLUDED: Skipping OOS incident for SKU '{sku}' (matches pattern '{excluded_pattern}') - Order {order_number}")
                        skip_item = True
                        break
                if skip_item:
                    continue
            vendor = product.get("vendor", "")
            product_type = product.get("productType", "")
            quantity = item.get("quantity", 1)
            
            # Check if this exact incident already exists to prevent duplicates
            existing_incident = db.query(OutOfStockIncident).filter(
                OutOfStockIncident.user_id == user_id,
                OutOfStockIncident.order_id == order_id,
                OutOfStockIncident.product_id == product_id,
                OutOfStockIncident.variant_id == variant_id,
                OutOfStockIncident.rule_name == rule_name,
                OutOfStockIncident.attempted_location_id == attempted_location_id
            ).first()
            
            if existing_incident:
                logger.info(f"OOS incident already exists for {combined_product_title} (SKU: {sku}) in order {order_number} for rule {rule_name}")
                continue
            
            # Create OOS incident record
            oos_incident = OutOfStockIncident(
                user_id=user_id,
                store_id=store_id,
                order_id=order_id,
                order_number=order_number,
                product_id=product_id,
                variant_id=variant_id,
                product_title=combined_product_title,
                variant_title=variant_title,
                sku=sku,
                vendor=vendor,
                product_type=product_type,
                quantity_attempted=quantity,
                attempted_location_id=attempted_location_id,
                attempted_location_alias=attempted_location_alias,
                rule_name=rule_name,
                incident_date=incident_date
            )
            
            db.add(oos_incident)
        
        db.commit()
        logger.info(f"Recorded OOS incidents for {len(line_items)} products in order {order_number}")
        
    except Exception as e:
        logger.error(f"Failed to record OOS incident for order {order.get('name', 'Unknown')}: {str(e)}")
        db.rollback()

def _record_oos_incident_for_failed_items(
    db: Session,
    user_id: int,
    store_id: int, 
    order: Dict,
    rule_name: str,
    attempted_location_id: str,
    attempted_location_alias: str = None,
    failed_items: List[Dict] = None,
    excluded_skus: List[str] = None
):
    """Record out-of-stock incidents for specific failed items from partial fulfillment"""
    try:
        order_id = order["id"]
        order_number = order.get("name", "Unknown")
        incident_date = datetime.now(timezone.utc)
        
        if not failed_items:
            logger.warning(f"No failed items provided for OOS incident recording for order {order_number}")
            return
        
        excluded_skus = excluded_skus or []
        
        for failed_item in failed_items:
            # Extract product information from failed item data
            product_id = failed_item.get("product_id", "")
            variant_id = failed_item.get("variant_id", "")
            base_product_title = failed_item.get("product_title", "Unknown Product")
            sku = failed_item.get("sku", "")
            variant_title = ""
            
            # Get missing data from original order (SKU and variant title)
            if variant_id:
                line_items = order.get("lineItems", {}).get("edges", [])
                for item_edge in line_items:
                    item_variant = item_edge["node"].get("variant", {})
                    if item_variant.get("id") == variant_id:
                        if not sku:
                            sku = item_variant.get("sku", "")
                            logger.info(f"Retrieved missing SKU from order data: {sku} for variant {variant_id}")
                        variant_title = item_variant.get("title", "")
                        # Filter out "Default Title" - store as empty string instead
                        if variant_title == "Default Title":
                            variant_title = ""
                        break
                        
                if not sku:
                    logger.warning(f"Could not find SKU for variant {variant_id} in order data - exclusion check may be compromised")
            
            # Combine product and variant titles
            combined_product_title = _combine_product_and_variant_title(base_product_title, variant_title)
            
            # Skip excluded SKUs
            if sku and excluded_skus:
                skip_item = False
                for excluded_pattern in excluded_skus:
                    if excluded_pattern.lower() in sku.lower():
                        logger.info(f"✅ EXCLUDED: Skipping OOS incident for SKU '{sku}' (matches pattern '{excluded_pattern}') - Order {order_number}")
                        skip_item = True
                        break
                if skip_item:
                    continue
            failed_quantity = failed_item.get("failed_quantity", 1)
            
            # Check if this exact incident already exists to prevent duplicates
            existing_incident = db.query(OutOfStockIncident).filter(
                OutOfStockIncident.user_id == user_id,
                OutOfStockIncident.order_id == order_id,
                OutOfStockIncident.product_id == product_id,
                OutOfStockIncident.variant_id == variant_id,
                OutOfStockIncident.rule_name == rule_name,
                OutOfStockIncident.attempted_location_id == attempted_location_id
            ).first()
            
            if existing_incident:
                logger.info(f"OOS incident already exists for {combined_product_title} (SKU: {sku}) in order {order_number} for rule {rule_name}")
                continue
            
            # Create OOS incident record for failed item
            oos_incident = OutOfStockIncident(
                user_id=user_id,
                store_id=store_id,
                order_id=order_id,
                order_number=order_number,
                product_id=product_id,
                variant_id=variant_id,
                product_title=combined_product_title,
                variant_title=variant_title,
                sku=sku,
                vendor="",  # Not available in failed_item data
                product_type="",  # Not available in failed_item data
                quantity_attempted=failed_quantity,
                attempted_location_id=attempted_location_id,
                attempted_location_alias=attempted_location_alias,
                rule_name=rule_name,
                incident_date=incident_date
            )
            
            db.add(oos_incident)
        
        db.commit()
        logger.info(f"Recorded OOS incidents for {len(failed_items)} failed items in order {order_number}")
        
    except Exception as e:
        logger.error(f"Failed to record OOS incident for failed items in order {order.get('name', 'Unknown')}: {str(e)}")
        db.rollback()

def _record_oos_incident_for_unavailable_items(
    db: Session,
    user_id: int,
    store_id: int, 
    order: Dict,
    rule_name: str,
    attempted_location_id: str,
    attempted_location_alias: str = None,
    unavailable_items: List[Dict] = None,
    excluded_skus: List[str] = None
):
    """Record out-of-stock incidents for items that were unavailable during inventory pre-check"""
    try:
        order_id = order["id"]
        order_number = order.get("name", "Unknown")
        incident_date = datetime.now(timezone.utc)
        
        if not unavailable_items:
            logger.warning(f"No unavailable items provided for OOS incident recording for order {order_number}")
            return
        
        excluded_skus = excluded_skus or []
        
        for unavailable_item in unavailable_items:
            # Extract product information from inventory check data
            base_product_title = unavailable_item.get("product_title", "Unknown Product")
            variant_id = unavailable_item.get("variant_id", "")
            sku = unavailable_item.get("sku", "")
            variant_title = ""
            
            # Skip excluded SKUs
            if sku and excluded_skus:
                skip_item = False
                for excluded_pattern in excluded_skus:
                    if excluded_pattern.lower() in sku.lower():
                        logger.info(f"✅ EXCLUDED: Skipping OOS incident for SKU '{sku}' (matches pattern '{excluded_pattern}') - Order {order_number}")
                        skip_item = True
                        break
                if skip_item:
                    continue
            required_quantity = unavailable_item.get("required_quantity", 1)
            available_quantity = unavailable_item.get("available_quantity", 0)
            
            # For unavailable items from inventory check, we may not have all product details
            # Extract product_id and variant_title from order line items for more complete data
            product_id = ""
            if variant_id:
                line_items = order.get("lineItems", {}).get("edges", [])
                for item_edge in line_items:
                    item = item_edge["node"]
                    if item.get("variant", {}).get("id") == variant_id:
                        product = item.get("product", {})
                        product_id = product.get("id", "")
                        variant_title = item.get("variant", {}).get("title", "")
                        # Filter out "Default Title" - store as empty string instead
                        if variant_title == "Default Title":
                            variant_title = ""
                        # Use more complete product info from order line items
                        if not base_product_title or base_product_title == "Unknown Product":
                            base_product_title = item.get("title", "Unknown Product")
                        break
            
            # Combine product and variant titles
            combined_product_title = _combine_product_and_variant_title(base_product_title, variant_title)
            
            # Create OOS incident record for unavailable item
            oos_incident = OutOfStockIncident(
                user_id=user_id,
                store_id=store_id,
                order_id=order_id,
                order_number=order_number,
                product_id=product_id,
                variant_id=variant_id,
                product_title=combined_product_title,
                variant_title=variant_title,
                sku=sku,
                vendor="",  # May not be available in inventory check data
                product_type="",  # May not be available in inventory check data
                quantity_attempted=required_quantity,
                attempted_location_id=attempted_location_id,
                attempted_location_alias=attempted_location_alias,
                rule_name=rule_name,
                incident_date=incident_date
            )
            
            db.add(oos_incident)
        
        db.commit()
        logger.info(f"Recorded OOS incidents for {len(unavailable_items)} unavailable items in order {order_number}")
        
    except Exception as e:
        logger.error(f"Failed to record OOS incident for unavailable items in order {order.get('name', 'Unknown')}: {str(e)}")
        db.rollback()

async def _check_inventory_availability(
    client: ShopifyClient,
    fulfillment_order: Dict,
    target_location_id: str,
    order_name: str,
    excluded_skus: List[str] = None
) -> Dict[str, Any]:
    """Check if all products in fulfillment order are available at target location"""
    try:
        logger.info(f"Checking inventory availability for order {order_name} at location {target_location_id}")
        
        line_items = fulfillment_order.get("lineItems", {}).get("edges", [])
        available_items = []
        unavailable_items = []
        
        # Debug: log the fulfillment order structure to understand the issue
        logger.debug(f"Fulfillment order structure for {order_name}: {fulfillment_order}")
        logger.info(f"Found {len(line_items)} line items in fulfillment order for {order_name}")
        
        # If no line items found, this is suspicious - fail the check
        if len(line_items) == 0:
            logger.error(f"No line items found in fulfillment order for {order_name} - this should not happen!")
            return {
                "all_available": False,
                "available_items": [],
                "unavailable_items": [],
                "total_items": 0,
                "error": "No line items found in fulfillment order"
            }
        
        excluded_skus = excluded_skus or []
        
        for item_edge in line_items:
            item = item_edge["node"]
            variant = item.get("variant", {})
            product = variant.get("product", {})
            
            product_title = product.get("title", "Unknown Product")
            variant_id = variant.get("id", "")
            sku = variant.get("sku", "")
            required_quantity = item.get("totalQuantity", 1)
            
            # Skip excluded SKUs from inventory check (they'll still be included in fulfillment move)
            if sku and excluded_skus:
                skip_item = False
                for excluded_pattern in excluded_skus:
                    if excluded_pattern.lower() in sku.lower():
                        logger.info(f"Skipping inventory check for excluded SKU: {sku} (matches pattern '{excluded_pattern}') - will be included in fulfillment anyway")
                        # Add to available items so it doesn't block fulfillment
                        available_items.append({
                            "product_title": product_title,
                            "variant_id": variant_id,
                            "sku": sku,
                            "required_quantity": required_quantity,
                            "available_quantity": "excluded_sku",
                            "skipped_from_check": True
                        })
                        skip_item = True
                        break
                if skip_item:
                    continue
            
            logger.info(f"Checking inventory for: {product_title} (SKU: {sku}), variant: {variant_id}, required: {required_quantity}")
            
            try:
                # Check inventory level at target location for this variant
                inventory_available = await client.check_inventory_at_location(
                    variant_id, target_location_id
                )
                
                item_info = {
                    "product_title": product_title,
                    "variant_id": variant_id,
                    "sku": sku,
                    "required_quantity": required_quantity,
                    "available_quantity": inventory_available
                }
                
                if inventory_available >= required_quantity:
                    available_items.append(item_info)
                    logger.info(f"✓ {product_title} (SKU: {sku}): {inventory_available} >= {required_quantity}")
                else:
                    unavailable_items.append(item_info)
                    logger.warning(f"✗ {product_title} (SKU: {sku}): {inventory_available} < {required_quantity}")
                    
            except Exception as item_error:
                logger.error(f"Failed to check inventory for {product_title} (SKU: {sku}): {str(item_error)}")
                # Don't assume unavailable on API errors - let fulfillment attempt be the source of truth
                # API errors (timeouts, network issues) should not trigger false OOS incidents
                logger.warning(f"Inventory check failed for {product_title} - will attempt fulfillment anyway to determine actual availability")
                # Add to available_items to allow fulfillment attempt (conservative approach)
                available_items.append({
                    "product_title": product_title,
                    "variant_id": variant_id,
                    "sku": sku,
                    "required_quantity": required_quantity,
                    "available_quantity": "unknown_due_to_api_error",
                    "check_error": str(item_error)
                })
        
        all_available = len(unavailable_items) == 0 and len(line_items) > 0
        
        logger.info(f"Inventory check for order {order_name}: {len(available_items)} available, {len(unavailable_items)} unavailable, all_available: {all_available}")
        
        return {
            "all_available": all_available,
            "available_items": available_items,
            "unavailable_items": unavailable_items,
            "total_items": len(line_items)
        }
        
    except Exception as e:
        logger.error(f"Failed to check inventory availability for order {order_name}: {str(e)}")
        # Don't assume unavailable on broad API failures - let fulfillment attempt proceed
        # This prevents false OOS incidents due to temporary API issues
        logger.warning(f"Inventory check system failed for order {order_name} - will attempt fulfillment anyway")
        return {
            "all_available": True,  # Conservative: allow fulfillment attempt
            "available_items": [],
            "unavailable_items": [],
            "total_items": 0,
            "check_error": str(e),
            "note": "Inventory check failed - fulfillment will determine actual availability"
        }

def resolve_location_alias(alias_name: str, store_id: int, db: Session) -> str | None:
    """Resolve a location alias to the actual Shopify location ID for a specific store"""
    mapping = db.query(LocationMapping).join(LocationAlias).filter(
        LocationAlias.alias_name == alias_name,
        LocationMapping.store_id == store_id,
        LocationMapping.is_active == True,
        LocationAlias.is_active == True
    ).first()
    
    return mapping.shopify_location_id if mapping else None

def create_task_status(task_id: str, task_name: str, status: str = "pending", user_id: int = None):
    """Create task status record"""
    db = get_db()
    try:
        # Check if task already exists
        existing_task = db.query(TaskStatus).filter(TaskStatus.task_id == task_id).first()
        if existing_task:
            logger.warning(f"Task {task_id} already exists, updating status instead")
            existing_task.status = status
            existing_task.started_at = datetime.now(timezone.utc) if status == "running" else None
            if user_id and not existing_task.user_id:
                existing_task.user_id = user_id
        else:
            task_status = TaskStatus(
                task_id=task_id,
                task_name=task_name,
                status=status,
                user_id=user_id,
                started_at=datetime.now(timezone.utc) if status == "running" else None
            )
            db.add(task_status)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to create task status: {str(e)}")
    finally:
        db.close()

def update_task_status(task_id: str, status: str, result: Dict = None, error_message: str = None):
    """Update task status record"""
    db = get_db()
    try:
        task_status = db.query(TaskStatus).filter(TaskStatus.task_id == task_id).first()
        if task_status:
            task_status.status = status
            task_status.result = result
            task_status.error_message = error_message
            if status in ["success", "failed"]:
                task_status.completed_at = datetime.now(timezone.utc)
            db.commit()
    except Exception as e:
        logger.error(f"Failed to update task status: {str(e)}")
    finally:
        db.close()

def cleanup_stale_tasks(max_age_hours: int = 24) -> Dict[str, int]:
    """Clean up stale tasks that are stuck in running state
    
    Args:
        max_age_hours: Maximum age in hours for a running task before considering it stale
        
    Returns:
        Dictionary with cleanup statistics
    """
    db = get_db()
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        
        # Find stale running tasks
        stale_tasks = db.query(TaskStatus).filter(
            TaskStatus.status == "running",
            TaskStatus.started_at < cutoff_time
        ).all()
        
        stale_count = len(stale_tasks)
        
        # Mark stale tasks as failed
        for task in stale_tasks:
            task.status = "failed"
            task.error_message = f"Task marked as stale after {max_age_hours} hours"
            task.completed_at = datetime.now(timezone.utc)
            logger.warning(f"Marking stale task {task.task_id} ({task.task_name}) as failed - started at {task.started_at}")
        
        db.commit()
        
        logger.info(f"Cleaned up {stale_count} stale tasks")
        
        return {
            "stale_tasks_cleaned": stale_count,
            "cutoff_time": cutoff_time.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to cleanup stale tasks: {str(e)}")
        db.rollback()
        return {
            "stale_tasks_cleaned": 0,
            "error": str(e)
        }
    finally:
        db.close()

async def _process_fraud_rules_for_order(
    order_data: Dict[str, Any], 
    store: ShopifyStore, 
    db: Session, 
    shopify_client = None,
    order_created_at: str = None
) -> Optional[Dict[str, Any]]:
    """Process fraud detection rules for an order.
    
    This function is isolated from order processing rules to ensure it doesn't
    affect the main order processing pipeline if it fails.
    
    Args:
        order_data: Raw order data from Shopify
        store: ShopifyStore instance
        db: Database session
        order_created_at: Order creation timestamp
        
    Returns:
        Dictionary with fraud processing results or None if failed
    """
    # CRITICAL: Create a new database session for fraud processing to ensure isolation
    fraud_db = SessionLocal()
    
    try:
        order_name = order_data.get('name', 'Unknown')
        logger.info(f"Starting fraud analysis and rule processing for order {order_name}")
        
        # Get user and store from fraud DB session
        fraud_store = fraud_db.query(ShopifyStore).filter(ShopifyStore.id == store.id).first()
        if not fraud_store:
            logger.error(f"Store not found in fraud session for store {store.id}")
            return None
            
        user = fraud_db.query(User).filter(User.id == fraud_store.user_id).first()
        if not user:
            logger.error(f"User not found for store {fraud_store.id}")
            return None
        
        # First, run fraud analysis with isolated session
        fraud_service = FraudAnalysisService(fraud_db, fraud_store, user)
        fraud_analysis = fraud_service.analyze_order_fraud(order_data)
        
        if not fraud_analysis:
            logger.warning(f"Fraud analysis failed for order {order_name}")
            return {
                "fraud_analysis_completed": False,
                "fraud_rules_processed": False,
                "error": "Fraud analysis failed"
            }
        
        logger.info(f"Fraud analysis completed for order {order_name} (ID: {fraud_analysis.id})")
        
        # CRITICAL: Ensure fraud analysis is fully committed and refreshed before rule processing
        fraud_db.commit()  # Ensure all changes are committed
        fraud_db.refresh(fraud_analysis)  # Refresh to get latest data from DB
        
        logger.info(f"🔄 FRAUD ANALYSIS REFRESHED before rule processing:")
        logger.info(f"  - duplicate_within_7days: {fraud_analysis.duplicate_within_7days}")
        logger.info(f"  - customer_name: {fraud_analysis.customer_name}")
        logger.info(f"  - is_first_time_customer: {fraud_analysis.is_first_time_customer}")
        
        # Then, run fraud detection rules
        # Create shopify_client if not provided
        if shopify_client is None:
            from shopify_client import ShopifyClient
            shopify_client = ShopifyClient(store.shop_domain, store.access_token)
        
        fraud_results = await process_fraud_rules_for_order_async(
            fraud_db, user, fraud_store, shopify_client, order_data, fraud_analysis
        )
        
        logger.info(f"Fraud rule processing completed for order {order_name}: "
                   f"{fraud_results.get('rules_matched', 0)} rules matched, "
                   f"{fraud_results.get('actions_executed', 0)} actions executed")
        
        # Create ProcessedFraudOrder record to prevent reprocessing
        try:
            order_id = order_data.get('id', '')
            processed_fraud_order = ProcessedFraudOrder(
                store_id=fraud_store.id,
                order_id=order_id,
                fraud_analysis_id=fraud_analysis.id,
                rules_applied=fraud_results.get('rules_matched', 0)
            )
            fraud_db.add(processed_fraud_order)
            fraud_db.commit()
            logger.info(f"Created ProcessedFraudOrder record for order {order_name}")
        except Exception as e:
            # If there's a duplicate key error, it means the order was already processed
            # This is fine - just log and continue
            if "UNIQUE constraint failed" in str(e) or "duplicate key" in str(e).lower():
                logger.info(f"Order {order_name} already has ProcessedFraudOrder record (concurrent processing detected)")
            else:
                logger.error(f"Failed to create ProcessedFraudOrder record: {str(e)}")
                # Don't fail the whole process, but rollback just this transaction
                fraud_db.rollback()
        
        return {
            "fraud_analysis_completed": True,
            "fraud_analysis_id": fraud_analysis.id,
            "fraud_rules_processed": True,
            "fraud_results": fraud_results
        }
        
    except Exception as e:
        logger.error(f"Error in fraud processing for order {order_data.get('name', 'Unknown')}: {str(e)}")
        # Log the error but don't raise it - fraud processing should not break order processing
        
        try:
            # Create error log entry
            order_name = order_data.get('name', 'Unknown')
            # Try to log error in main session, but don't fail if it doesn't work
            try:
                _log_order_action(
                    db, store.user_id, store.id, order_data.get('id', ''),
                    order_name, "fraud_processing_error", "error",
                    error_message=str(e),
                    order_created_at=order_created_at
                )
            except Exception as inner_log_error:
                logger.error(f"Failed to log fraud processing error to main session: {str(inner_log_error)}")
        except Exception as log_error:
            logger.error(f"Failed to log fraud processing error: {str(log_error)}")
        
        return {
            "fraud_analysis_completed": False,
            "fraud_rules_processed": False,
            "error": str(e)
        }
    finally:
        # CRITICAL: Always close the isolated fraud session
        try:
            fraud_db.close()
            logger.info("Closed isolated fraud processing database session")
        except Exception as close_error:
            logger.error(f"Error closing fraud database session: {str(close_error)}")

@celery.task(bind=True)
def test_celery_connection(self):
    """Test task to verify Celery is working"""
    task_id = self.request.id
    create_task_status(task_id, "test_celery_connection", "running")
    
    try:
        logger.info("Celery worker is running successfully!")
        update_task_status(task_id, "success", {"message": "Celery is working"})
        return {"status": "success", "message": "Celery worker is running"}
    except Exception as e:
        logger.error(f"Celery test failed: {str(e)}")
        update_task_status(task_id, "failed", error_message=str(e))
        raise

@celery.task(bind=True)
def process_store_orders(self, user_id: int, store_id: int):
    """Process orders for a specific store"""
    task_id = self.request.id
    create_task_status(task_id, "process_store_orders", "running", user_id=user_id)
    
    db = get_db()
    try:
        # Get store and user
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == user_id,
            ShopifyStore.is_active == True
        ).first()
        
        if not store:
            raise ValueError(f"Store {store_id} not found or inactive")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User {user_id} not found")
        
        # Get active rules for user (order by priority ascending: 0, 1, 2, 3...)
        rules = db.query(ProcessingRule).filter(
            ProcessingRule.user_id == user_id,
            ProcessingRule.is_active == True
        ).order_by(ProcessingRule.priority.asc()).all()
        
        if not rules:
            logger.info(f"No active rules found for user {user_id}")
            update_task_status(task_id, "success", {"processed_orders": 0, "message": "No active rules"})
            return
        
        # Run async order processing
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                _process_store_orders_async(store, rules, db)
            )
            update_task_status(task_id, "success", result)
            
            # Update store last sync time
            store.last_sync = datetime.now(timezone.utc)
            db.commit()
            
            return result
            
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"Failed to process store orders: {str(e)}")
        update_task_status(task_id, "failed", error_message=str(e))
        raise
    finally:
        db.close()

async def _process_store_orders_async(store: ShopifyStore, rules: List[ProcessingRule], db: Session):
    """Async function to process store orders"""
    client = ShopifyClient(store.shop_domain, store.access_token)
    rule_engine = RuleEngine()
    
    # Get excluded SKUs for this user
    excluded_skus_query = db.query(ExcludedSKU).filter(
        ExcludedSKU.user_id == store.user_id,
        ExcludedSKU.is_active == True
    ).all()
    excluded_sku_patterns = [sku.sku_pattern for sku in excluded_skus_query]
    
    if excluded_sku_patterns:
        logger.info(f"Loaded {len(excluded_sku_patterns)} excluded SKU patterns for user {store.user_id}: {excluded_sku_patterns}")
    else:
        logger.info(f"No excluded SKU patterns found for user {store.user_id}")
    
    # Get user's sync window setting (default to 7 days if not set)
    settings = db.query(Settings).filter(Settings.user_id == store.user_id).first()
    sync_window_days = settings.sync_window_days if settings and settings.sync_window_days else 7
    
    # Use configurable sync window instead of hardcoded 24 hours
    sync_cutoff = datetime.now(timezone.utc) - timedelta(days=sync_window_days)
    sync_cutoff_date = sync_cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Also use last sync for efficiency (if available)
    if store.last_sync:
        last_sync_date = store.last_sync.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        last_sync_date = sync_cutoff_date
    
    # Use the earlier date for API filtering to ensure we get all relevant orders
    api_cutoff_date = min(sync_cutoff_date, last_sync_date)
    
    processed_orders = 0
    cursor = None
    
    logger.info(f"Processing orders for store {store.shop_domain}")
    logger.info(f"  - Sync window: {sync_window_days} days (cutoff: {sync_cutoff_date})")
    logger.info(f"  - Last sync: {last_sync_date}")
    logger.info(f"  - API filter date: {api_cutoff_date}")
    logger.info(f"  - Will process orders that are: (newer than {sync_window_days}d cutoff OR newer than last sync) AND unfulfilled AND not already processed")
    
    try:
        while True:
            # Fetch orders using the earlier cutoff date to ensure we get all relevant orders
            # Include fraud data since we need it for fraud analysis after rule processing
            orders_data = await client.get_orders(
                limit=50,
                created_at_min=api_cutoff_date,
                cursor=cursor,
                include_fraud_data=True
            )
            
            orders = orders_data["edges"]
            if not orders:
                break
            
            for order_edge in orders:
                order = order_edge["node"]
                order_id = order["id"]
                order_number = order["name"]
                order_created_at = order["createdAt"]
                fulfillment_status = order.get("displayFulfillmentStatus", "")
                
                # First check: Only process orders with "UNFULFILLED" status (skip fulfilled and cancelled)
                # Note: Cancelled orders have fulfillment status of "CANCELLED", not "UNFULFILLED"
                if fulfillment_status != "UNFULFILLED":
                    if fulfillment_status == "CANCELLED":
                        logger.debug(f"Order {order_number} is cancelled, skipping")
                    else:
                        logger.debug(f"Order {order_number} has fulfillment status '{fulfillment_status}', skipping (only processing UNFULFILLED orders)")
                    continue
                
                # Second check: Skip if order was already processed (avoid duplicates)
                existing = db.query(ProcessedOrder).filter(
                    ProcessedOrder.store_id == store.id,
                    ProcessedOrder.order_id == order_id
                ).first()
                
                if existing:
                    logger.debug(f"Order {order_number} already processed, skipping")
                    continue
                
                # Third check: Date filtering - process if within sync window OR newer than last sync
                order_date = datetime.fromisoformat(order_created_at.replace('Z', '+00:00'))
                sync_cutoff_date_obj = datetime.fromisoformat(sync_cutoff_date.replace('Z', '+00:00'))
                last_sync_date_obj = datetime.fromisoformat(last_sync_date.replace('Z', '+00:00'))
                
                # Skip orders older than sync window AND older than last sync
                if order_date < sync_cutoff_date_obj and order_date < last_sync_date_obj:
                    logger.debug(f"Order {order_number} created before both {sync_window_days}d cutoff ({sync_cutoff_date}) and last sync ({last_sync_date}), skipping")
                    continue
                
                logger.info(f"Order {order_number}: created {order_created_at}, status '{fulfillment_status}' - processing")
                
                try:
                    # Apply rules to order
                    rules_applied = False
                    current_order = order  # Start with the initial order data
                    
                    for rule in rules:
                        # Evaluate rule against current order state
                        if rule_engine.evaluate_rule(rule, current_order, excluded_sku_patterns, store):
                            rules_applied = True
                            logger.info(f"Rule '{rule.name}' (priority {rule.priority}) matched for order {order_number}")
                            
                            # Apply rule actions and wait for completion
                            success = await _apply_rule_actions(
                                client, rule, current_order, store, db, excluded_sku_patterns
                            )
                            
                            # Rule matched and was applied (regardless of success/failure)
                            _log_order_action(
                                db, store.user_id, store.id, order_id, 
                                order_number, f"applied_rule_{rule.id}", 
                                "match", {"rule_name": rule.name, "actions_successful": success},
                                order_created_at=order_created_at
                            )
                            
                            # ALWAYS re-fetch order after a rule matches and executes (regardless of success/failure)
                            # This ensures the next rule sees any changes from this rule
                            # Include fraud data for the fraud analysis that happens after all rules
                            logger.info(f"Re-fetching order {order_number} to get updated state after rule '{rule.name}'")
                            refreshed_order = await client.get_order_by_id(order_id, include_fraud_data=True)
                            
                            if refreshed_order:
                                current_order = refreshed_order
                                logger.info(f"Order {order_number} refreshed - tags: {current_order.get('tags', [])}")
                            else:
                                logger.warning(f"Failed to refresh order {order_number}, continuing with current state")
                            
                            # Get delay from rule or use default
                            delay_ms = getattr(rule, 'delay_ms', 500)  # Default 500ms if not set
                            delay_seconds = delay_ms / 1000.0
                            
                            # Delay to ensure Shopify has fully processed the changes
                            logger.info(f"Waiting {delay_ms}ms before next rule...")
                            await asyncio.sleep(delay_seconds)
                    
                    # CRITICAL: Ensure order state is fully committed before fraud processing
                    db.commit()
                    logger.info(f"Committed order changes for {order_number} before fraud processing")
                    
                    # Add small delay to ensure database propagation
                    await asyncio.sleep(0.2)  # 200ms delay
                    logger.info(f"Applied 200ms delay before fraud processing for order {order_number}")
                    
                    # Process fraud detection rules after order processing rules
                    await _process_fraud_rules_for_order(
                        current_order, store, db, client, order_created_at
                    )
                    
                    # Mark order as processed with race condition handling
                    try:
                        processed_order = ProcessedOrder(
                            store_id=store.id,
                            order_id=order_id
                        )
                        db.add(processed_order)
                        db.commit()
                    except IntegrityError as e:
                        db.rollback()
                        # This is expected in race conditions between workers
                        logger.info(f"Order {order_number} already marked as processed by another worker")
                        # Continue processing since the order is already marked
                    except Exception as e:
                        db.rollback()
                        # Re-raise other exceptions to be handled by outer try-except
                        raise
                    
                    # Log if no rules were applied
                    if not rules_applied:
                        _log_order_action(
                            db, store.user_id, store.id, order_id,
                            order_number, "no_rules_matched", "skipped",
                            {"message": "No rules matched this order"},
                            order_created_at=order_created_at
                        )
                    
                    processed_orders += 1
                    
                except IntegrityError as e:
                    # Rollback the session if there's any database error
                    db.rollback()
                    # This can happen if the order was processed between our check and insert
                    logger.info(f"Order {order_number} was already processed by another worker (race condition)")
                    continue
                except Exception as e:
                    # Rollback the session if there's any database error
                    db.rollback()
                    
                    logger.error(f"Error processing order {order_number}: {str(e)}")
                    _log_order_action(
                        db, store.user_id, store.id, order_id, 
                        order_number, "processing_error", "error", 
                        error_message=str(e),
                        order_created_at=order_created_at
                    )
            
            # Check for next page
            page_info = orders_data["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            
            cursor = page_info["endCursor"]
    
    except Exception as e:
        logger.error(f"Error fetching orders from {store.shop_domain}: {str(e)}")
        raise
    
    return {
        "processed_orders": processed_orders,
        "store_domain": store.shop_domain
    }

async def _apply_rule_actions(
    client: ShopifyClient, 
    rule: ProcessingRule, 
    order: Dict, 
    store: ShopifyStore, 
    db: Session,
    excluded_skus: List[str] = None
) -> bool:
    """Apply rule actions to an order"""
    success = True
    
    for action in rule.actions:
        try:
            action_type = action["type"]
            parameters = action["parameters"]
            
            if action_type == "add_tag":
                tags = parameters.get("tags", [])
                if isinstance(tags, str):
                    tags = [tags]
                
                result = await client.add_tags_to_order(order["id"], tags)
                if not result:
                    success = False
                    
            elif action_type == "remove_tag":
                tags = parameters.get("tags", [])
                if isinstance(tags, str):
                    tags = [tags]
                
                logger.info(f"Removing tags {tags} from order {order.get('name', order.get('id'))}")
                result = await client.remove_tags_from_order(order["id"], tags)
                logger.info(f"Remove tags result: {result}")
                if not result:
                    success = False
                    
            elif action_type == "set_fulfillment_location":
                # Support both old format (location_id) and new format (location_alias)
                location_id = parameters.get("location_id")
                location_alias = parameters.get("location_alias")
                
                logger.info(f"Processing fulfillment action for order {order.get('name', order.get('id'))}")
                
                # If using alias, resolve it to location_id
                if location_alias:
                    logger.info(f"Resolving location alias: {location_alias}")
                    location_id = resolve_location_alias(location_alias, store.id, db)
                    if location_id:
                        logger.info(f"Resolved alias '{location_alias}' to location ID: {location_id}")
                    else:
                        logger.error(f"No mapping found for alias '{location_alias}' in store {store.shop_name}")
                        success = False
                        continue
                elif location_id:
                    logger.info(f"Using direct location ID: {location_id}")
                else:
                    logger.error("No location_id or location_alias provided for set_fulfillment_location action")
                    success = False
                    continue
                
                if location_id:
                    # Get fulfillment orders for this order
                    fulfillment_orders = order.get("fulfillmentOrders", {}).get("edges", [])
                    logger.info(f"Found {len(fulfillment_orders)} fulfillment orders")
                    
                    # PHASE 1: Check inventory for ALL fulfillment orders first (true all-or-nothing)
                    # If ANY fulfillment order fails inventory check, skip ALL moves
                    moveable_fulfillment_orders = []
                    all_order_inventory_available = True
                    all_unavailable_items = []
                    
                    for fo_edge in fulfillment_orders:
                        fo = fo_edge["node"]
                        logger.info(f"Fulfillment order {fo['id']} status: {fo['status']}")
                        
                        if fo["status"].upper() in ["OPEN", "SCHEDULED"]:
                            # Pre-check: Verify ALL products are available at target location (all-or-nothing policy)
                            # Note: Pass None for excluded_skus to ensure ALL products are checked for fulfillment
                            inventory_check = await _check_inventory_availability(
                                client, fo, location_id, order.get("name", "Unknown"), None
                            )
                            
                            if not inventory_check["all_available"]:
                                # This fulfillment order has unavailable items
                                all_order_inventory_available = False
                                all_unavailable_items.extend(inventory_check["unavailable_items"])
                                logger.warning(f"Fulfillment order {fo['id']} has {len(inventory_check['unavailable_items'])} unavailable items")
                            else:
                                # This fulfillment order is available for moving
                                moveable_fulfillment_orders.append(fo)
                                logger.info(f"Fulfillment order {fo['id']} passed inventory check")
                    
                    # PHASE 2: Apply true all-or-nothing policy across entire order
                    if not all_order_inventory_available:
                        # Some products across ANY fulfillment order not available - skip ALL moves
                        logger.warning(f"All-or-nothing policy: Skipping ALL fulfillment moves for order {order.get('name', 'Unknown')} - {len(all_unavailable_items)} products not available across {len(fulfillment_orders)} fulfillment orders")
                        
                        # Log fulfillment failure as informational - rule still matched successfully
                        _log_order_action(
                            db, store.user_id, store.id, order["id"], 
                            order.get("name", "Unknown"), "fulfillment_move_failed", 
                            "info", 
                            {
                                "rule_name": rule.name,
                                "target_location_id": location_id,
                                "location_alias": location_alias or "direct_id",
                                "policy": "all_or_nothing_across_entire_order",
                                "pre_check_failed": True,
                                "total_fulfillment_orders": len(fulfillment_orders),
                                "unavailable_items": all_unavailable_items,
                                "reason": "out_of_stock"
                            },
                            error_message=f"All-or-nothing policy: {len(all_unavailable_items)} products not available across order, skipped ALL fulfillment moves"
                        )
                        
                        # Add OOS tag to order due to all-or-nothing policy trigger
                        try:
                            await client.add_tags_to_order(order["id"], ["OOS"])
                            logger.info(f"Added OOS tag to order {order.get('name', order['id'])} due to all-or-nothing policy (pre-check failure)")
                        except Exception as tag_error:
                            logger.error(f"Failed to add OOS tag to order: {str(tag_error)}")
                        
                        # Record incidents for ONLY unavailable products (not all products)
                        try:
                            # Record OOS incidents for items that failed inventory pre-check
                            # Since inventory checks are now reliable, these represent real stock issues
                            _record_oos_incident_for_unavailable_items(
                                db=db,
                                user_id=store.user_id,
                                store_id=store.id,
                                order=order,
                                rule_name=rule.name,
                                attempted_location_id=location_id,
                                attempted_location_alias=location_alias,
                                unavailable_items=all_unavailable_items,
                                excluded_skus=excluded_skus
                            )
                            logger.info(f"Recorded OOS incidents for {len(all_unavailable_items)} items that failed pre-check across entire order")
                            
                        except Exception as record_error:
                            logger.error(f"Failed to record OOS incidents for all-or-nothing pre-check failure: {str(record_error)}")
                        
                        success = False
                        # Skip ALL fulfillment orders due to all-or-nothing policy
                        
                    else:
                        # PHASE 3: All fulfillment orders passed inventory checks - proceed with moves
                        logger.info(f"All-or-nothing pre-check passed: All {len(moveable_fulfillment_orders)} fulfillment orders can be moved")
                        
                        for fo in moveable_fulfillment_orders:
                            logger.info(f"Moving fulfillment order {fo['id']} to location {location_id}")
                            result = await client.move_fulfillment_order(
                                fo["id"], location_id
                            )
                            
                            if result.get("partial_success"):
                                # Partial success detected - this violates all-or-nothing policy
                                moved_items = result.get("moved_items", [])
                                failed_items = result.get("failed_items", [])
                                
                                logger.warning(f"All-or-nothing policy violation for {fo['id']}: {len(moved_items)} items moved, {len(failed_items)} items failed")
                                logger.error(f"This should not happen with proper pre-checks! Some items were moved but others failed.")
                                
                                # Log as complete failure due to all-or-nothing policy violation
                                _log_order_action(
                                    db, store.user_id, store.id, order["id"], 
                                    order.get("name", "Unknown"), "fulfillment_move_failed", 
                                    "failed", 
                                    {
                                        "rule_name": rule.name,
                                        "target_location_id": location_id,
                                        "fulfillment_order_id": fo["id"],
                                        "location_alias": location_alias or "direct_id",
                                        "policy": "all_or_nothing",
                                        "policy_violation": True,
                                        "moved_items_count": len(moved_items),
                                        "failed_items_count": len(failed_items),
                                        "moved_items": moved_items,
                                        "failed_items": failed_items
                                    },
                                    error_message=f"All-or-nothing policy violation: {len(failed_items)} products failed after {len(moved_items)} were already moved. Manual intervention may be required."
                                )
                                
                                # Add OOS tag to order due to all-or-nothing policy violation
                                try:
                                    await client.add_tags_to_order(order["id"], ["OOS"])
                                    logger.info(f"Added OOS tag to order {order.get('name', order['id'])} due to all-or-nothing policy violation (partial success)")
                                except Exception as tag_error:
                                    logger.error(f"Failed to add OOS tag to order: {str(tag_error)}")
                                
                                # Record incidents for ONLY the failed products (not moved ones)
                                try:
                                    # Record OOS incidents for ONLY the products that actually failed to move
                                    _record_oos_incident_for_failed_items(
                                        db=db,
                                        user_id=store.user_id,
                                        store_id=store.id,
                                        order=order,
                                        rule_name=rule.name,
                                        attempted_location_id=location_id,
                                        attempted_location_alias=location_alias,
                                        failed_items=failed_items,
                                        excluded_skus=excluded_skus
                                    )
                                    
                                except Exception as record_error:
                                    logger.error(f"Failed to record OOS incidents for all-or-nothing failure: {str(record_error)}")
                                
                                # Consider this as complete failure
                                success = False
                                    
                            elif not result["success"]:
                                # Complete failure - but check if it's because already at location
                                logger.error(f"Failed to move fulfillment order {fo['id']}: {result.get('errors', [])}")
                                
                                # Extract actual error messages from Shopify API response
                                shopify_errors = result.get("errors", [])
                                error_messages = []
                                is_already_at_location = False
                                
                                for error in shopify_errors:
                                    if isinstance(error, dict) and "message" in error:
                                        error_msg = error["message"]
                                        error_messages.append(error_msg)
                                        # Check if error is because already at target location
                                        if "Cannot move to the current origin location" in error_msg:
                                            is_already_at_location = True
                                
                                # If already at location, treat as success!
                                if is_already_at_location:
                                    logger.info(f"Fulfillment order {fo['id']} is already at the target location - treating as successful")
                                    
                                    # Log as successful since items are already where they need to be
                                    _log_order_action(
                                        db, store.user_id, store.id, order["id"], 
                                        order.get("name", "Unknown"), "fulfillment_already_at_location", 
                                        "success", 
                                        {
                                            "rule_name": rule.name,
                                            "target_location_id": location_id,
                                            "fulfillment_order_id": fo["id"],
                                            "location_alias": location_alias or "direct_id",
                                            "message": "Fulfillment order already at target location"
                                        }
                                    )
                                    # Don't set success = False, let it continue as if successful
                                    
                                else:
                                    # Real failure - not because of already being at location
                                    success = False
                                    
                                    # Use actual Shopify error messages or indicate unknown failure
                                    error_msg = " | ".join(error_messages) if error_messages else "Fulfillment move failed but Shopify provided no error details"
                                    
                                    _log_order_action(
                                        db, store.user_id, store.id, order["id"], 
                                        order.get("name", "Unknown"), "fulfillment_move_failed", 
                                        "info", 
                                        {
                                            "rule_name": rule.name,
                                            "target_location_id": location_id,
                                            "fulfillment_order_id": fo["id"],
                                            "location_alias": location_alias or "direct_id",
                                            "errors": result.get("errors", []),
                                            "reason": "out_of_stock"
                                        },
                                        error_message=error_msg
                                    )
                                    
                                    # Add OOS tag to order due to complete fulfillment failure
                                    try:
                                        await client.add_tags_to_order(order["id"], ["OOS"])
                                        logger.info(f"Added OOS tag to order {order.get('name', order['id'])} due to complete fulfillment failure")
                                    except Exception as tag_error:
                                        logger.error(f"Failed to add OOS tag to order: {str(tag_error)}")
                                    
                                    # Record OOS incident for out-of-stock fulfillment issues
                                    try:
                                        # Record OOS incident for all products since the entire fulfillment failed
                                        # (we don't have specific info about which products caused the failure)
                                        _record_oos_incident(
                                            db=db,
                                            user_id=store.user_id,
                                            store_id=store.id,
                                            order=order,
                                            rule_name=rule.name,
                                            attempted_location_id=location_id,
                                            attempted_location_alias=location_alias,
                                            excluded_skus=excluded_skus
                                        )
                                        
                                    except Exception as record_error:
                                        logger.error(f"Failed to record OOS incident: {str(record_error)}")
                                    
                            else:
                                # Complete success
                                moved_items = result.get("moved_items", [])
                                logger.info(f"Successfully moved fulfillment order {fo['id']} - {len(moved_items)} items moved")
                                
                                # Log successful fulfillment move
                                _log_order_action(
                                    db, store.user_id, store.id, order["id"], 
                                    order.get("name", "Unknown"), "fulfillment_moved", 
                                    "success", 
                                    {
                                        "rule_name": rule.name,
                                        "target_location_id": location_id,
                                        "fulfillment_order_id": fo["id"],
                                        "location_alias": location_alias or "direct_id",
                                        "moved_items_count": len(moved_items),
                                        "moved_items": moved_items
                                    }
                                )
                        else:
                            logger.info(f"Skipping fulfillment order {fo['id']} with status {fo['status']}")
            
        except Exception as e:
            logger.error(f"Error applying action {action_type}: {str(e)}")
            success = False
    
    return success

def _log_order_action(
    db: Session, 
    user_id: int, 
    store_id: int, 
    order_id: str, 
    order_number: str, 
    action: str, 
    status: str, 
    details: Dict = None, 
    error_message: str = None,
    order_created_at: str = None
):
    """Log order processing action"""
    try:
        # Use actual order creation time if provided, otherwise use current time
        created_at = None
        if order_created_at:
            try:
                from datetime import datetime, timezone
                # Parse Shopify ISO timestamp and ensure it stays timezone-aware in UTC
                created_at = datetime.fromisoformat(order_created_at.replace('Z', '+00:00'))
                # Explicitly convert to UTC timezone to ensure it's timezone-aware
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                else:
                    created_at = created_at.astimezone(timezone.utc)
                print(f"DEBUG: Using order creation time: {created_at} (timezone: {created_at.tzinfo}) for order {order_number}")
            except Exception as parse_error:
                print(f"DEBUG: Failed to parse order_created_at '{order_created_at}': {parse_error}")
                # Fall back to timezone-aware current time
                created_at = datetime.now(timezone.utc)
        
        if created_at:
            log_entry = OrderLog(
                user_id=user_id,
                store_id=store_id,
                order_id=order_id,
                order_number=order_number,
                action=action,
                status=status,
                details=details,
                error_message=error_message,
                created_at=created_at
            )
        else:
            # Use timezone-aware current time as fallback
            from datetime import datetime, timezone
            created_at = datetime.now(timezone.utc)
            log_entry = OrderLog(
                user_id=user_id,
                store_id=store_id,
                order_id=order_id,
                order_number=order_number,
                action=action,
                status=status,
                details=details,
                error_message=error_message,
                created_at=created_at
            )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log order action: {str(e)}")

@celery.task(bind=True)
def process_all_orders_if_enabled(self):
    """Check if auto-sync is enabled and process orders if needed"""
    db = get_db()
    try:
        # Proactively clean up stale tasks before starting new ones
        stale_cleanup_result = cleanup_stale_tasks(max_age_hours=12)
        if stale_cleanup_result.get("stale_tasks_cleaned", 0) > 0:
            logger.info(f"Cleaned up {stale_cleanup_result['stale_tasks_cleaned']} stale tasks before processing orders")
        
        # Get all users with auto-sync enabled
        users_with_settings = db.query(User).join(Settings).filter(
            Settings.auto_sync_enabled == True
        ).all()
        
        for user in users_with_settings:
            settings = user.settings
            if not settings:
                continue
                
            # Check if it's time to sync based on user's frequency setting
            stores = db.query(ShopifyStore).filter(
                ShopifyStore.user_id == user.id,
                ShopifyStore.is_active == True
            ).all()
            
            for store in stores:
                # Check if last sync was longer ago than sync frequency
                should_sync = False
                if not store.last_sync:
                    should_sync = True
                else:
                    # Handle both timezone-aware and naive datetimes
                    if store.last_sync.tzinfo is None:
                        # Convert naive datetime to UTC
                        last_sync_utc = store.last_sync.replace(tzinfo=timezone.utc)
                    else:
                        last_sync_utc = store.last_sync
                    
                    time_since_sync = datetime.now(timezone.utc) - last_sync_utc
                    if time_since_sync.total_seconds() >= settings.sync_frequency_minutes * 60:
                        should_sync = True
                
                if should_sync:
                    logger.info(f"Queueing sync for store {store.shop_domain}")
                    process_store_orders.delay(user.id, store.id)
        
        return {"message": "Auto-sync check completed"}
        
    except Exception as e:
        logger.error(f"Failed to check auto-sync: {str(e)}")
        raise
    finally:
        db.close()

@celery.task(bind=True)
def process_fraud_detection_if_enabled(self):
    """Check if fraud detection is enabled and process orders if needed"""
    db = get_db()
    try:
        # Proactively clean up stale tasks before starting new ones
        stale_cleanup_result = cleanup_stale_tasks(max_age_hours=12)
        if stale_cleanup_result.get("stale_tasks_cleaned", 0) > 0:
            logger.info(f"Cleaned up {stale_cleanup_result['stale_tasks_cleaned']} stale tasks before fraud detection")
        
        # Get all users with fraud sync enabled
        users_with_settings = db.query(User).join(Settings).filter(
            Settings.fraud_sync_enabled == True
        ).all()
        
        for user in users_with_settings:
            settings = user.settings
            if not settings:
                continue
                
            # Check if it's time to sync based on user's frequency setting
            stores = db.query(ShopifyStore).filter(
                ShopifyStore.user_id == user.id,
                ShopifyStore.is_active == True
            ).all()
            
            for store in stores:
                # Check if last sync was longer ago than sync frequency
                should_sync = False
                if not store.last_sync:
                    should_sync = True
                else:
                    # Handle both timezone-aware and naive datetimes
                    if store.last_sync.tzinfo is None:
                        # Convert naive datetime to UTC
                        last_sync_utc = store.last_sync.replace(tzinfo=timezone.utc)
                    else:
                        last_sync_utc = store.last_sync
                    
                    time_since_sync = datetime.now(timezone.utc) - last_sync_utc
                    if time_since_sync.total_seconds() >= settings.sync_frequency_minutes * 60:
                        should_sync = True
                
                if should_sync:
                    logger.info(f"Queueing fraud detection for store {store.shop_domain}")
                    process_store_fraud_detection.delay(user.id, store.id)
        
        return {"message": "Fraud detection check completed"}
        
    except Exception as e:
        logger.error(f"Failed to check fraud detection sync: {str(e)}")
        raise
    finally:
        db.close()

@celery.task(bind=True)
def process_all_orders(self):
    """Process orders for all active stores"""
    task_id = self.request.id
    create_task_status(task_id, "process_all_orders", "running")
    
    db = get_db()
    try:
        # Get all active stores
        stores = db.query(ShopifyStore).filter(ShopifyStore.is_active == True).all()
        
        results = []
        for store in stores:
            try:
                # Queue individual store processing task
                task = process_store_orders.delay(store.user_id, store.id)
                results.append({
                    "store_id": store.id,
                    "store_domain": store.shop_domain,
                    "task_id": task.id
                })
            except Exception as e:
                logger.error(f"Failed to queue task for store {store.shop_domain}: {str(e)}")
                results.append({
                    "store_id": store.id,
                    "store_domain": store.shop_domain,
                    "error": str(e)
                })
        
        update_task_status(task_id, "success", {"queued_stores": len(results), "results": results})
        return results
        
    except Exception as e:
        logger.error(f"Failed to process all orders: {str(e)}")
        update_task_status(task_id, "failed", error_message=str(e))
        raise
    finally:
        db.close()

@celery.task(bind=True)
def process_store_fraud_detection(self, user_id: int, store_id: int):
    """Process fraud detection for a specific store independently"""
    task_id = self.request.id
    create_task_status(task_id, "process_store_fraud_detection", "running", user_id=user_id)
    
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    db = get_db()
    try:
        logger.info(f"Starting fraud detection task for store_id={store_id}, user_id={user_id}")
        
        # Get the store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == user_id
        ).first()
        
        if not store:
            error_msg = f"Store {store_id} not found for user {user_id}"
            logger.error(error_msg)
            update_task_status(task_id, "failed", error_message=error_msg)
            raise ValueError(error_msg)
        
        # Get user settings
        settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        if not settings:
            settings = Settings(user_id=user_id)
            db.add(settings)
            db.commit()
            db.refresh(settings)
        
        # Calculate date range for fetching orders
        # For regular syncs, use a smaller window to avoid rate limiting
        # Only look back further if store hasn't been synced in a while
        end_date = datetime.now(timezone.utc)
        
        # Determine how far back to look
        if not store.last_sync:
            # First sync - look back duplicate_detection_days
            fraud_sync_days = min(settings.duplicate_detection_days, 7)  # Cap at 7 days for initial sync
        else:
            # Regular sync - only look back since last sync + buffer
            time_since_sync = end_date - store.last_sync
            fraud_sync_days = min(
                max(time_since_sync.days + 1, 1),  # At least 1 day, or days since last sync + 1
                7  # Cap at 7 days to avoid rate limiting
            )
        
        start_date = end_date - timedelta(days=fraud_sync_days)
        
        # Initialize Shopify client
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        # Fetch recent orders with proper pagination
        all_orders = []
        cursor = None
        orders_fetched = 0
        
        # Format dates for Shopify query
        start_date_str = start_date.isoformat()
        
        # Limit total orders to process in a single run
        max_orders = 125  # Process up to 125 orders per sync to avoid timeouts
        
        logger.info(f"Starting fraud detection sync for store {store.shop_domain}, looking back {fraud_sync_days} days")
        
        while orders_fetched < max_orders:
            try:
                # Use pageInfo for proper cursor-based pagination
                orders_data = loop.run_until_complete(
                    client.get_orders(
                        created_at_min=start_date_str,
                        limit=25,  # Shopify recommends smaller page sizes for better performance
                        cursor=cursor,
                        include_fraud_data=True
                    )
                )
                
                if not orders_data or "edges" not in orders_data:
                    break
                    
                edges = orders_data["edges"]
                if not edges:
                    break
                    
                # Extract nodes from edges
                new_orders = [edge["node"] for edge in edges]
                all_orders.extend(new_orders)
                orders_fetched += len(new_orders)
                
                # Check PageInfo for next page
                page_info = orders_data.get("pageInfo", {})
                has_next_page = page_info.get("hasNextPage", False)
                
                if has_next_page and orders_fetched < max_orders:
                    # Use endCursor from pageInfo for next request
                    cursor = page_info.get("endCursor")
                    if not cursor:
                        logger.warning("No endCursor found despite hasNextPage=True")
                        break
                    
                    # Add delay between requests to respect rate limits
                    # Shopify allows 2 requests per second for GraphQL Admin API
                    loop.run_until_complete(asyncio.sleep(0.6))  # ~1.6 requests per second
                else:
                    break
                    
            except Exception as e:
                error_str = str(e)
                if "THROTTLED" in error_str or "MAX_COST_EXCEEDED" in error_str:
                    logger.warning(f"Rate limited while fetching orders, stopping at {orders_fetched} orders")
                    # Wait a bit before continuing with what we have
                    loop.run_until_complete(asyncio.sleep(2))
                    break
                else:
                    logger.error(f"Error fetching orders: {error_str}")
                    raise
        
        logger.info(f"Fetched {len(all_orders)} orders for fraud detection from store {store.shop_domain} (using {fraud_sync_days} day window)")
        
        # Process each order for fraud detection only
        processed_count = 0
        skipped_fulfilled = 0
        skipped_cancelled = 0
        for order in all_orders:
            try:
                # Skip fulfilled and cancelled orders - only process UNFULFILLED orders
                fulfillment_status = order.get("displayFulfillmentStatus", "")
                if fulfillment_status != "UNFULFILLED":
                    if fulfillment_status == "CANCELLED":
                        logger.debug(f"Order {order.get('name')} is cancelled, skipping fraud detection")
                        skipped_cancelled += 1
                    else:
                        logger.debug(f"Order {order.get('name')} has fulfillment status '{fulfillment_status}', skipping fraud detection (only processing UNFULFILLED orders)")
                        skipped_fulfilled += 1
                    continue
                
                # Check if we already processed fraud detection for this order
                order_id = order.get("id")
                processed_fraud_order = db.query(ProcessedFraudOrder).filter(
                    ProcessedFraudOrder.store_id == store_id,
                    ProcessedFraudOrder.order_id == order_id
                ).first()
                
                # Skip if already processed
                if processed_fraud_order:
                    logger.debug(f"Order {order.get('name')} already processed for fraud detection, skipping")
                    continue
                
                # Run full fraud analysis and rule processing for new orders
                order_created_at = order.get("createdAt")
                result = loop.run_until_complete(
                    _process_fraud_rules_for_order(
                        order, store, db, client, order_created_at
                    )
                )
                
                if result and result.get("fraud_analysis_completed"):
                    processed_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to process fraud detection for order {order.get('name', 'Unknown')}: {str(e)}")
                continue
        
        # Update last sync time
        store.last_sync = datetime.now(timezone.utc)
        db.commit()
        
        update_task_status(task_id, "completed", result={
            "store_id": store_id,
            "orders_analyzed": processed_count,
            "unfulfilled_orders": len(all_orders) - skipped_fulfilled - skipped_cancelled,
            "fulfilled_orders_skipped": skipped_fulfilled,
            "cancelled_orders_skipped": skipped_cancelled,
            "total_orders": len(all_orders)
        })
        
        logger.info(f"Completed fraud detection for store {store.shop_domain}: {processed_count} orders analyzed, {skipped_fulfilled} fulfilled orders skipped, {skipped_cancelled} cancelled orders skipped, {len(all_orders)} total orders fetched")
        
        return {
            "store_id": store_id,
            "orders_analyzed": processed_count,
            "unfulfilled_orders": len(all_orders) - skipped_fulfilled - skipped_cancelled,
            "fulfilled_orders_skipped": skipped_fulfilled,
            "cancelled_orders_skipped": skipped_cancelled,
            "total_orders": len(all_orders)
        }
        
    except Exception as e:
        error_msg = f"Failed to process fraud detection for store {store_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)  # Add full traceback to logs
        try:
            # Ensure error is properly saved to task status
            update_task_status(task_id, "failed", error_message=error_msg)
        except Exception as update_error:
            logger.error(f"Failed to update task status: {str(update_error)}")
        raise
    finally:
        try:
            loop.close()
        except Exception as loop_error:
            logger.error(f"Failed to close event loop: {str(loop_error)}")
        try:
            db.close()
        except Exception as db_error:
            logger.error(f"Failed to close database: {str(db_error)}")

@celery.task(bind=True)
def cleanup_old_logs(self):
    """Clean up old order logs, task status records, and archived fraud analyses"""
    task_id = self.request.id
    create_task_status(task_id, "cleanup_old_logs", "running")
    
    db = get_db()
    try:
        from fraud_archive_service import FraudArchiveService
        
        # Get all users to check their retention settings
        all_users = db.query(User).all()
        deleted_archived_analyses = {}
        
        # Clean up archived fraud analyses based on each user's retention settings
        for user in all_users:
            # Get user's retention settings
            user_settings = db.query(Settings).filter(Settings.user_id == user.id).first()
            retention_days = user_settings.log_retention_days if user_settings else 30
            
            # Delete old archived analyses for this user
            archive_service = FraudArchiveService(db)
            deleted_count = archive_service.cleanup_old_archived_analyses(user.id, retention_days)
            
            if deleted_count > 0:
                deleted_archived_analyses[user.email] = deleted_count
        
        # Delete logs older than 30 days (default for system logs)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
        
        deleted_logs = db.query(OrderLog).filter(
            OrderLog.created_at < cutoff_date
        ).delete()
        
        # Clean up stale running tasks first (before deleting old tasks)
        stale_cleanup_result = cleanup_stale_tasks(max_age_hours=24)
        stale_tasks_cleaned = stale_cleanup_result.get("stale_tasks_cleaned", 0)
        
        # Delete task status records older than 7 days
        task_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        deleted_tasks = db.query(TaskStatus).filter(
            TaskStatus.created_at < task_cutoff
        ).delete()
        
        db.commit()
        
        result = {
            "deleted_logs": deleted_logs,
            "deleted_task_records": deleted_tasks,
            "stale_tasks_cleaned": stale_tasks_cleaned,
            "deleted_archived_analyses": deleted_archived_analyses,
            "total_archived_analyses_deleted": sum(deleted_archived_analyses.values()),
            "cutoff_date": cutoff_date.isoformat()
        }
        
        update_task_status(task_id, "success", result)
        logger.info(f"Cleanup completed: {result}")
        
        return result
        
    except Exception as e:
        logger.error(f"Cleanup failed: {str(e)}")
        update_task_status(task_id, "failed", error_message=str(e))
        raise
    finally:
        db.close()

@celery.task(bind=True)
def test_store_connection(self, store_id: int):
    """Test connection to a Shopify store"""
    task_id = self.request.id
    create_task_status(task_id, "test_store_connection", "running")
    
    db = get_db()
    try:
        store = db.query(ShopifyStore).filter(ShopifyStore.id == store_id).first()
        if not store:
            raise ValueError(f"Store {store_id} not found")
        
        # Run async connection test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            client = ShopifyClient(store.shop_domain, store.access_token)
            shop_info = loop.run_until_complete(client.get_shop_info())
            
            result = {
                "status": "success",
                "shop_name": shop_info.get("name"),
                "domain": shop_info.get("domain"),
                "plan": shop_info.get("plan", {}).get("displayName")
            }
            
            update_task_status(task_id, "success", result)
            return result
            
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"Store connection test failed: {str(e)}")
        update_task_status(task_id, "failed", error_message=str(e))
        raise
    finally:
        db.close()

@celery.task(bind=True)
def archive_fulfilled_fraud_analyses(self):
    """Archive fraud analyses for orders that are fulfilled or cancelled"""
    task_id = self.request.id
    create_task_status(task_id, "archive_fulfilled_fraud_analyses", "running")
    
    db = get_db()
    try:
        # Get all users with fraud sync enabled
        users_with_fraud_enabled = db.query(User).join(Settings).filter(
            Settings.fraud_sync_enabled == True
        ).all()
        
        if not users_with_fraud_enabled:
            logger.info("No users with fraud sync enabled")
            result = {"message": "No users with fraud sync enabled"}
            update_task_status(task_id, "success", result)
            return result
        
        # Archive analyses for each user
        total_archived = 0
        total_failed = 0
        user_results = []
        
        # Run async archival for each user
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            archive_service = FraudArchiveService(db)
            
            for user in users_with_fraud_enabled:
                try:
                    logger.info(f"Archiving fraud analyses for user {user.id}")
                    
                    # Archive fulfilled and cancelled analyses
                    archive_result = loop.run_until_complete(
                        archive_service.archive_fulfilled_and_cancelled_analyses(user.id)
                    )
                    
                    total_archived += archive_result["archived"]
                    total_failed += archive_result["failed"]
                    
                    user_results.append({
                        "user_id": user.id,
                        "email": user.email,
                        **archive_result
                    })
                    
                except Exception as e:
                    logger.error(f"Error archiving for user {user.id}: {str(e)}")
                    total_failed += 1
                    user_results.append({
                        "user_id": user.id,
                        "email": user.email,
                        "error": str(e)
                    })
        
        finally:
            loop.close()
        
        result = {
            "total_archived": total_archived,
            "total_failed": total_failed,
            "users_processed": len(users_with_fraud_enabled),
            "user_results": user_results
        }
        
        update_task_status(task_id, "success", result)
        logger.info(f"Archive task completed: {result}")
        
        return result
        
    except Exception as e:
        logger.error(f"Archive task failed: {str(e)}")
        update_task_status(task_id, "failed", error_message=str(e))
        raise
    finally:
        db.close()

async def retry_order_processing(order_ids: List[str], rule_id: Optional[int], user_id: int, db: Session):
    """Retry processing specific orders with all rules or a specific rule"""
    processed_count = 0
    failed_count = 0
    
    # Get user's active rules
    if rule_id:
        logger.info(f"Retrying with specific rule ID: {rule_id}")
        rules = db.query(ProcessingRule).filter(
            ProcessingRule.id == rule_id,
            ProcessingRule.user_id == user_id,
            ProcessingRule.is_active == True
        ).all()
        if not rules:
            raise ValueError(f"Rule {rule_id} not found or inactive")
        logger.info(f"Found specific rule: {rules[0].name}")
    else:
        logger.info("Retrying with all active rules")
        rules = db.query(ProcessingRule).filter(
            ProcessingRule.user_id == user_id,
            ProcessingRule.is_active == True
        ).order_by(ProcessingRule.priority.asc()).all()
        logger.info(f"Found {len(rules)} active rules: {[r.name for r in rules]}")
    
    if not rules:
        raise ValueError("No active rules found")
    
    # Get user's stores for order lookup
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == user_id,
        ShopifyStore.is_active == True
    ).all()
    
    if not stores:
        raise ValueError("No active stores found")
    
    # Get excluded SKUs for this user
    excluded_skus_query = db.query(ExcludedSKU).filter(
        ExcludedSKU.user_id == user_id,
        ExcludedSKU.is_active == True
    ).all()
    excluded_sku_patterns = [sku.sku_pattern for sku in excluded_skus_query]
    
    if excluded_sku_patterns:
        logger.info(f"Loaded {len(excluded_sku_patterns)} excluded SKU patterns for retry processing: {excluded_sku_patterns}")
    
    rule_engine = RuleEngine()
    
    for order_id in order_ids:
        try:
            # Find which store this order belongs to by trying each store
            order_data = None
            store = None
            
            for s in stores:
                client = ShopifyClient(s.shop_domain, s.access_token)
                order_data = await client.get_order_by_id(order_id)
                if order_data:
                    store = s
                    break
            
            if not order_data or not store:
                logger.error(f"Order {order_id} not found in any store")
                _log_order_action(
                    db, user_id, 0, order_id, "Unknown", "retry_processing", "failed",
                    {"retry_type": "specific_rule" if rule_id else "all_rules", "rule_id": rule_id},
                    error_message="Order not found in any connected store"
                )
                failed_count += 1
                continue
            
            # Apply rules to the order
            rules_applied = False
            client = ShopifyClient(store.shop_domain, store.access_token)
            
            logger.info(f"Found {len(rules)} active rules for retry processing")
            for rule in rules:
                logger.info(f"Evaluating rule '{rule.name}' (ID: {rule.id}) for order {order_data.get('name', 'Unknown')}")
                if rule_engine.evaluate_rule(rule, order_data, excluded_sku_patterns, store):
                    rules_applied = True
                    logger.info(f"Rule '{rule.name}' matched! Applying actions...")
                    success = await _apply_rule_actions(client, rule, order_data, store, db, excluded_sku_patterns)
                    
                    # Log retry attempt - rule matched regardless of action success
                    _log_order_action(
                        db, user_id, store.id, order_id, 
                        order_data.get("name", "Unknown"), "retry_processing", 
                        "match",
                        {
                            "retry_type": "specific_rule" if rule_id else "all_rules",
                            "rule_id": rule_id,
                            "rule_name": rule.name,
                            "applied_rule_id": rule.id,
                            "actions_successful": success
                        }
                    )
                else:
                    logger.info(f"Rule '{rule.name}' did not match order {order_data.get('name', 'Unknown')}")
            
            # Log if no rules matched
            if not rules_applied:
                _log_order_action(
                    db, user_id, store.id, order_id,
                    order_data.get("name", "Unknown"), "retry_processing", "skipped",
                    {
                        "retry_type": "specific_rule" if rule_id else "all_rules", 
                        "rule_id": rule_id,
                        "message": "No rules matched this order"
                    }
                )
            
            processed_count += 1
            
        except Exception as e:
            logger.error(f"Error retrying order {order_id}: {str(e)}")
            _log_order_action(
                db, user_id, 0, order_id, "Unknown", "retry_processing", "error",
                {"retry_type": "specific_rule" if rule_id else "all_rules", "rule_id": rule_id},
                error_message=str(e)
            )
            failed_count += 1
    
    return {
        "processed_count": processed_count,
        "failed_count": failed_count,
        "total_count": len(order_ids)
    }


@celery.task(bind=True)
def trigger_fraud_analysis_all_recent(self, user_id: int, days_back: int = 7):
    """Trigger fraud analysis for all recent orders across all user stores"""
    task_id = self.request.id
    create_task_status(task_id, "trigger_fraud_analysis", "running", user_id=user_id)
    
    db = get_db()
    try:
        # Get user and their stores
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User {user_id} not found")
        
        stores = db.query(ShopifyStore).filter(
            ShopifyStore.user_id == user_id,
            ShopifyStore.is_active == True
        ).all()
        
        if not stores:
            update_task_status(task_id, "completed", {"message": "No active stores found"})
            return {"message": "No active stores found", "processed_count": 0}
        
        # Calculate date range using user's timezone
        
        # Get user's timezone settings
        user_settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        user_timezone = user_settings.timezone if user_settings and user_settings.timezone else "UTC"
        
        # Calculate date range using user's timezone
        user_tz = pytz.timezone(user_timezone)
        now_user_tz = datetime.now(user_tz)
        since_date_user_tz = now_user_tz - timedelta(days=days_back)
        since_date = since_date_user_tz.astimezone(timezone.utc)
        
        logger.info(f"Using user timezone {user_timezone}: {days_back} days back from {now_user_tz.strftime('%Y-%m-%d %H:%M:%S %Z')} = {since_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        total_processed = 0
        total_failed = 0
        store_results = []
        
        for store in stores:
            try:
                logger.info(f"Processing fraud analysis for store {store.shop_domain}")
                
                # Run async order processing
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    client = ShopifyClient(store.shop_domain, store.access_token)
                    
                    # Fetch ALL recent orders with fraud data using pagination
                    all_orders = []
                    cursor = None
                    page_count = 0
                    
                    while True:
                        page_count += 1
                        logger.info(f"Fetching page {page_count} of orders for store {store.shop_domain}")
                        
                        orders_response = loop.run_until_complete(
                            client.get_orders(
                                limit=20,  # Reduced from 50 to stay under GraphQL cost limit when including fraud data
                                created_at_min=since_date.isoformat(),
                                cursor=cursor,
                                include_fraud_data=True
                            )
                        )
                        
                        if not orders_response or "edges" not in orders_response:
                            logger.warning(f"No orders found for store {store.shop_domain} on page {page_count}")
                            break
                        
                        # Extract orders from current page
                        page_orders = [edge["node"] for edge in orders_response["edges"]]
                        all_orders.extend(page_orders)
                        
                        logger.info(f"Fetched {len(page_orders)} orders on page {page_count} (total so far: {len(all_orders)})")
                        
                        # Check if there are more pages
                        page_info = orders_response.get("pageInfo", {})
                        has_next_page = page_info.get("hasNextPage", False)
                        
                        if not has_next_page:
                            logger.info(f"Completed pagination for store {store.shop_domain} - fetched {len(all_orders)} total orders across {page_count} pages")
                            break
                        
                        cursor = page_info.get("endCursor")
                        if not cursor:
                            logger.warning(f"No endCursor found but hasNextPage=True for store {store.shop_domain}")
                            break
                    
                    if not all_orders:
                        logger.warning(f"No orders found for store {store.shop_domain}")
                        continue
                    
                    # Process all fetched orders
                    orders = all_orders
                    store_processed = 0
                    store_failed = 0
                    
                    for order in orders:
                        try:
                            # Check if fraud analysis already exists
                            existing_analysis = db.query(FraudAnalysis).filter(
                                FraudAnalysis.shopify_order_id == order["id"],
                                FraudAnalysis.user_id == user_id
                            ).first()
                            
                            if existing_analysis:
                                logger.info(f"Fraud analysis already exists for order {order.get('name', order['id'])} - re-analyzing with fresh data")
                                
                                # Delete existing analysis to force fresh analysis
                                db.delete(existing_analysis)
                                db.commit()
                                logger.info(f"Deleted existing fraud analysis for order {order.get('name')} to allow fresh analysis")
                            
                            # Run fraud analysis
                            result = loop.run_until_complete(
                                _process_fraud_rules_for_order(
                                    order, store, db, client
                                )
                            )
                            
                            if result and result.get("fraud_analysis_completed"):
                                store_processed += 1
                                total_processed += 1
                            else:
                                store_failed += 1
                                total_failed += 1
                        
                        except Exception as e:
                            logger.error(f"Error processing fraud analysis for order {order.get('id')}: {str(e)}")
                            store_failed += 1
                            total_failed += 1
                    
                    store_results.append({
                        "store_name": store.shop_domain,
                        "processed": store_processed,
                        "failed": store_failed
                    })
                    
                finally:
                    loop.close()
                    
            except Exception as e:
                logger.error(f"Error processing store {store.shop_domain}: {str(e)}")
                store_results.append({
                    "store_name": store.shop_domain,
                    "processed": 0,
                    "failed": 1,
                    "error": str(e)
                })
                total_failed += 1
        
        result = {
            "message": "Fraud analysis completed",
            "processed_count": total_processed,
            "failed_count": total_failed,
            "stores": store_results,
            "days_back": days_back
        }
        
        update_task_status(task_id, "success", result)
        return result
        
    except Exception as e:
        logger.error(f"Fraud analysis task failed: {str(e)}")
        update_task_status(task_id, "failed", error_message=str(e))
        raise
    finally:
        db.close()


@celery.task(bind=True) 
def reprocess_fraud_rules_recent(self, user_id: int, days_back: int = 7):
    """Reprocess fraud rules for recent fraud analyses"""
    task_id = self.request.id
    create_task_status(task_id, "reprocess_fraud_rules", "running", user_id=user_id)
    
    db = get_db()
    try:
        # Get user and their stores
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User {user_id} not found")
        
        # Calculate date range using user's timezone
        
        # Get user's timezone settings
        user_settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        user_timezone = user_settings.timezone if user_settings and user_settings.timezone else "UTC"
        
        # Calculate date range using user's timezone
        user_tz = pytz.timezone(user_timezone)
        now_user_tz = datetime.now(user_tz)
        since_date_user_tz = now_user_tz - timedelta(days=days_back)
        since_date = since_date_user_tz.astimezone(timezone.utc)
        
        # Get recent fraud analyses
        fraud_analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == user_id,
            FraudAnalysis.analysis_timestamp >= since_date
        ).all()
        
        if not fraud_analyses:
            result = {"message": "No recent fraud analyses found", "processed_count": 0}
            update_task_status(task_id, "success", result)
            return result
        
        total_processed = 0
        total_failed = 0
        store_results = {}
        
        for analysis in fraud_analyses:
            try:
                # Get the store for this analysis
                store = db.query(ShopifyStore).filter(
                    ShopifyStore.id == analysis.store_id
                ).first()
                
                if not store:
                    logger.warning(f"Store not found for fraud analysis {analysis.id}")
                    continue
                
                # Get the original order data
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    client = ShopifyClient(store.shop_domain, store.access_token)
                    # Add global ID prefix if not already present
                    order_id = analysis.shopify_order_id
                    if not order_id.startswith('gid://'):
                        order_id = f"gid://shopify/Order/{order_id}"
                    
                    order_data = loop.run_until_complete(
                        client.get_order_by_id(order_id, include_fraud_data=True)
                    )
                    
                    if not order_data:
                        logger.warning(f"Order data not found for fraud analysis {analysis.id}")
                        continue
                    
                    # Re-calculate duplicate detection with updated settings
                    logger.info(f"Re-calculating duplicate detection for order {analysis.order_name}")
                    
                    # Refresh the database session to ensure we have the latest settings
                    db.expire_all()
                    db.commit()
                    
                    # Get fresh user settings
                    fresh_settings = db.query(Settings).filter(Settings.user_id == user.id).first()
                    logger.info(f"Using duplicate_detection_days: {fresh_settings.duplicate_detection_days if fresh_settings else 7}")
                    
                    from fraud_service import FraudAnalysisService
                    fraud_service = FraudAnalysisService(db, store, user)
                    
                    # Update the duplicate detection field with new settings
                    try:
                        old_value = analysis.duplicate_within_7days
                        updated_duplicate = fraud_service._check_duplicate_within_configurable_days(order_data)
                        analysis.duplicate_within_7days = updated_duplicate
                        db.commit()
                        logger.info(f"Updated duplicate detection for order {analysis.order_name}: {old_value} -> {updated_duplicate}")
                        
                        # CRITICAL: Refresh the analysis object to ensure all changes are properly loaded
                        db.refresh(analysis)
                        logger.info(f"🔄 REFRESHED fraud analysis after duplicate update:")
                        logger.info(f"  - duplicate_within_7days: {analysis.duplicate_within_7days}")
                        logger.info(f"  - customer_name: {analysis.customer_name}")
                        logger.info(f"  - is_first_time_customer: {analysis.is_first_time_customer}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to update duplicate detection for order {analysis.order_name}: {str(e)}")
                        # Continue processing even if duplicate detection update fails
                    
                    # Refresh the analysis to ensure we have the latest data
                    db.refresh(analysis)
                    logger.info(f"Before rule processing - duplicate_within_7days: {analysis.duplicate_within_7days}")
                    
                    # Reprocess fraud rules
                    from fraud_rule_processor import process_fraud_rules_for_order_async
                    
                    fraud_results = loop.run_until_complete(
                        process_fraud_rules_for_order_async(
                            db, user, store, client, order_data, analysis
                        )
                    )
                    
                    if fraud_results:
                        total_processed += 1
                        store_name = store.shop_domain
                        if store_name not in store_results:
                            store_results[store_name] = {"processed": 0, "failed": 0}
                        store_results[store_name]["processed"] += 1
                    else:
                        total_failed += 1
                        store_name = store.shop_domain
                        if store_name not in store_results:
                            store_results[store_name] = {"processed": 0, "failed": 0}
                        store_results[store_name]["failed"] += 1
                
                finally:
                    loop.close()
                    
            except Exception as e:
                logger.error(f"Error reprocessing fraud rules for analysis {analysis.id}: {str(e)}")
                total_failed += 1
                if store:
                    store_name = store.shop_domain
                    if store_name not in store_results:
                        store_results[store_name] = {"processed": 0, "failed": 0}
                    store_results[store_name]["failed"] += 1
        
        result = {
            "message": "Fraud rule reprocessing completed",
            "processed_count": total_processed,
            "failed_count": total_failed,
            "stores": [{"store_name": k, **v} for k, v in store_results.items()],
            "days_back": days_back
        }
        
        update_task_status(task_id, "success", result)
        return result
        
    except Exception as e:
        logger.error(f"Fraud rule reprocessing task failed: {str(e)}")
        update_task_status(task_id, "failed", error_message=str(e))
        raise
    finally:
        db.close()