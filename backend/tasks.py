from celery import Celery
from celery.schedules import crontab
import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from database import SessionLocal, engine
from models import User, ShopifyStore, ProcessingRule, OrderLog, TaskStatus, Settings, ProcessedOrder, LocationAlias, LocationMapping, OutOfStockIncident
from shopify_client import ShopifyClient
from rule_engine import RuleEngine

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
    'cleanup-old-logs': {
        'task': 'tasks.cleanup_old_logs',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },
}

def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

def _record_oos_incident(
    db: Session,
    user_id: int,
    store_id: int, 
    order: Dict,
    rule_name: str,
    attempted_location_id: str,
    attempted_location_alias: str = None
):
    """Record out-of-stock incidents for all products in an order"""
    try:
        order_id = order["id"]
        order_number = order.get("name", "Unknown")
        incident_date = datetime.utcnow()
        
        # Get line items from the order
        line_items = order.get("lineItems", {}).get("edges", [])
        
        for item_edge in line_items:
            item = item_edge["node"]
            product = item.get("product", {})
            variant = item.get("variant", {})
            
            # Extract product information
            product_id = product.get("id", "")
            variant_id = variant.get("id", "")
            product_title = item.get("title", "Unknown Product")
            variant_title = variant.get("title", "")
            sku = variant.get("sku", "")
            vendor = product.get("vendor", "")
            product_type = product.get("productType", "")
            quantity = item.get("quantity", 1)
            
            # Create OOS incident record
            oos_incident = OutOfStockIncident(
                user_id=user_id,
                store_id=store_id,
                order_id=order_id,
                order_number=order_number,
                product_id=product_id,
                variant_id=variant_id,
                product_title=product_title,
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
    failed_items: List[Dict] = None
):
    """Record out-of-stock incidents for specific failed items from partial fulfillment"""
    try:
        order_id = order["id"]
        order_number = order.get("name", "Unknown")
        incident_date = datetime.utcnow()
        
        if not failed_items:
            logger.warning(f"No failed items provided for OOS incident recording for order {order_number}")
            return
        
        for failed_item in failed_items:
            # Extract product information from failed item data
            product_id = failed_item.get("product_id", "")
            variant_id = failed_item.get("variant_id", "")
            product_title = failed_item.get("product_title", "Unknown Product")
            sku = failed_item.get("sku", "")
            failed_quantity = failed_item.get("failed_quantity", 1)
            
            # Create OOS incident record for failed item
            oos_incident = OutOfStockIncident(
                user_id=user_id,
                store_id=store_id,
                order_id=order_id,
                order_number=order_number,
                product_id=product_id,
                variant_id=variant_id,
                product_title=product_title,
                variant_title="",  # Not available in failed_item data
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
    unavailable_items: List[Dict] = None
):
    """Record out-of-stock incidents for items that were unavailable during inventory pre-check"""
    try:
        order_id = order["id"]
        order_number = order.get("name", "Unknown")
        incident_date = datetime.utcnow()
        
        if not unavailable_items:
            logger.warning(f"No unavailable items provided for OOS incident recording for order {order_number}")
            return
        
        for unavailable_item in unavailable_items:
            # Extract product information from inventory check data
            product_title = unavailable_item.get("product_title", "Unknown Product")
            variant_id = unavailable_item.get("variant_id", "")
            sku = unavailable_item.get("sku", "")
            required_quantity = unavailable_item.get("required_quantity", 1)
            available_quantity = unavailable_item.get("available_quantity", 0)
            
            # For unavailable items from inventory check, we may not have all product details
            # Extract product_id from variant_id if available
            product_id = ""
            if variant_id:
                # Try to extract from order line items for more complete data
                line_items = order.get("lineItems", {}).get("edges", [])
                for item_edge in line_items:
                    item = item_edge["node"]
                    if item.get("variant", {}).get("id") == variant_id:
                        product = item.get("product", {})
                        product_id = product.get("id", "")
                        # Use more complete product info from order line items
                        if not product_title or product_title == "Unknown Product":
                            product_title = item.get("title", "Unknown Product")
                        break
            
            # Create OOS incident record for unavailable item
            oos_incident = OutOfStockIncident(
                user_id=user_id,
                store_id=store_id,
                order_id=order_id,
                order_number=order_number,
                product_id=product_id,
                variant_id=variant_id,
                product_title=product_title,
                variant_title="",  # May not be available in inventory check data
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
    order_name: str
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
        
        for item_edge in line_items:
            item = item_edge["node"]
            variant = item.get("variant", {})
            product = variant.get("product", {})
            
            product_title = product.get("title", "Unknown Product")
            variant_id = variant.get("id", "")
            sku = variant.get("sku", "")
            required_quantity = item.get("totalQuantity", 1)
            
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
                # Assume unavailable if we can't check
                unavailable_items.append({
                    "product_title": product_title,
                    "variant_id": variant_id,
                    "sku": sku,
                    "required_quantity": required_quantity,
                    "available_quantity": 0,
                    "error": str(item_error)
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
        # Assume all unavailable if we can't check
        return {
            "all_available": False,
            "available_items": [],
            "unavailable_items": [],
            "total_items": 0,
            "error": str(e)
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

def create_task_status(task_id: str, task_name: str, status: str = "pending"):
    """Create task status record"""
    db = get_db()
    try:
        task_status = TaskStatus(
            task_id=task_id,
            task_name=task_name,
            status=status,
            started_at=datetime.utcnow() if status == "running" else None
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
                task_status.completed_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        logger.error(f"Failed to update task status: {str(e)}")
    finally:
        db.close()

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
    create_task_status(task_id, "process_store_orders", "running")
    
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
            store.last_sync = datetime.utcnow()
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
    
    # Always check orders from last 24 hours to catch any missed orders
    yesterday = datetime.utcnow() - timedelta(days=1)
    min_24h_date = yesterday.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Also use last sync for efficiency (if available)
    if store.last_sync:
        last_sync_date = store.last_sync.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        last_sync_date = min_24h_date
    
    processed_orders = 0
    cursor = None
    
    logger.info(f"Processing orders for store {store.shop_domain}")
    logger.info(f"  - 24h cutoff: {min_24h_date}")
    logger.info(f"  - Last sync: {last_sync_date}")
    logger.info(f"  - Will process orders that are: (newer than 24h cutoff OR newer than last sync) AND unfulfilled AND not already processed")
    
    try:
        while True:
            # Fetch orders
            # Note: Shopify GraphQL doesn't support date filtering in query parameter properly
            # So we fetch all orders and filter by date in our code
            orders_data = await client.get_orders(
                limit=50,
                created_at_min=None,
                cursor=cursor
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
                
                # First check: Only process orders with "UNFULFILLED" status
                if fulfillment_status != "UNFULFILLED":
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
                
                # Third check: Date filtering - process if within 24h OR newer than last sync
                order_date = datetime.fromisoformat(order_created_at.replace('Z', '+00:00'))
                min_24h_date_obj = datetime.fromisoformat(min_24h_date.replace('Z', '+00:00'))
                last_sync_date_obj = datetime.fromisoformat(last_sync_date.replace('Z', '+00:00'))
                
                # Skip orders older than 24 hours AND older than last sync
                if order_date < min_24h_date_obj and order_date < last_sync_date_obj:
                    logger.debug(f"Order {order_number} created before both 24h cutoff ({min_24h_date}) and last sync ({last_sync_date}), skipping")
                    continue
                
                logger.info(f"Order {order_number}: created {order_created_at}, status '{fulfillment_status}' - processing")
                
                try:
                    # Apply rules to order
                    rules_applied = False
                    current_order = order  # Start with the initial order data
                    
                    for rule in rules:
                        # Evaluate rule against current order state
                        if rule_engine.evaluate_rule(rule, current_order):
                            rules_applied = True
                            logger.info(f"Rule '{rule.name}' (priority {rule.priority}) matched for order {order_number}")
                            
                            # Apply rule actions and wait for completion
                            success = await _apply_rule_actions(
                                client, rule, current_order, store, db
                            )
                            
                            if success:
                                _log_order_action(
                                    db, store.user_id, store.id, order_id, 
                                    order_number, f"applied_rule_{rule.id}", 
                                    "success", {"rule_name": rule.name}
                                )
                                
                                # Re-fetch order to get updated state (tags, fulfillment status, etc.)
                                # This ensures the next rule sees the changes from this rule
                                logger.info(f"Re-fetching order {order_number} to get updated state after rule '{rule.name}'")
                                refreshed_order = await client.get_order_by_id(order_id)
                                
                                if refreshed_order:
                                    current_order = refreshed_order
                                    logger.info(f"Order {order_number} refreshed - tags: {current_order.get('tags', [])}")
                                else:
                                    logger.warning(f"Failed to refresh order {order_number}, continuing with current state")
                                
                                # Small delay to ensure Shopify has fully processed the changes
                                # This is especially important for tag operations
                                await asyncio.sleep(0.5)
                                
                            else:
                                _log_order_action(
                                    db, store.user_id, store.id, order_id, 
                                    order_number, f"applied_rule_{rule.id}", 
                                    "failed", {"rule_name": rule.name}
                                )
                                # Continue to next rule even if this one failed
                    
                    # Mark order as processed
                    processed_order = ProcessedOrder(
                        store_id=store.id,
                        order_id=order_id
                    )
                    db.add(processed_order)
                    db.commit()
                    
                    # Log if no rules were applied
                    if not rules_applied:
                        _log_order_action(
                            db, store.user_id, store.id, order_id,
                            order_number, "no_rules_matched", "info",
                            {"message": "No rules matched this order"}
                        )
                    
                    processed_orders += 1
                    
                except Exception as e:
                    logger.error(f"Error processing order {order_number}: {str(e)}")
                    _log_order_action(
                        db, store.user_id, store.id, order_id, 
                        order_number, "processing_error", "failed", 
                        error_message=str(e)
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
    db: Session
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
                    
                    for fo_edge in fulfillment_orders:
                        fo = fo_edge["node"]
                        logger.info(f"Fulfillment order {fo['id']} status: {fo['status']}")
                        
                        if fo["status"].upper() in ["OPEN", "SCHEDULED"]:
                            logger.info(f"Moving fulfillment order {fo['id']} to location {location_id}")
                            
                            # Pre-check: Verify ALL products are available at target location (all-or-nothing policy)
                            inventory_check = await _check_inventory_availability(
                                client, fo, location_id, order.get("name", "Unknown")
                            )
                            
                            if not inventory_check["all_available"]:
                                # Some products not available - skip the move entirely
                                logger.warning(f"All-or-nothing policy: Skipping fulfillment move for {fo['id']} - {len(inventory_check['unavailable_items'])} products not available at target location")
                                
                                # Log as complete failure due to all-or-nothing policy
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
                                        "pre_check_failed": True,
                                        "available_items": inventory_check["available_items"],
                                        "unavailable_items": inventory_check["unavailable_items"]
                                    },
                                    error_message=f"All-or-nothing policy: {len(inventory_check['unavailable_items'])} products not available at target location, skipped fulfillment move"
                                )
                                
                                # Add "OOS" tag and record incidents for ONLY unavailable products (not all products)
                                try:
                                    await client.add_tags_to_order(order["id"], ["OOS"])
                                    logger.info(f"Added OOS tag to order {order.get('name', order['id'])} due to all-or-nothing policy pre-check failure")
                                    
                                    # Record OOS incidents for ONLY the products that were actually unavailable
                                    _record_oos_incident_for_unavailable_items(
                                        db=db,
                                        user_id=store.user_id,
                                        store_id=store.id,
                                        order=order,
                                        rule_name=rule.name,
                                        attempted_location_id=location_id,
                                        attempted_location_alias=location_alias,
                                        unavailable_items=inventory_check["unavailable_items"]
                                    )
                                    
                                except Exception as tag_error:
                                    logger.error(f"Failed to add OOS tag for all-or-nothing pre-check failure: {str(tag_error)}")
                                
                                success = False
                                continue  # Skip to next fulfillment order
                            
                            # All products available - proceed with fulfillment move
                            logger.info(f"All-or-nothing pre-check passed: All {len(inventory_check['available_items'])} products available at target location")
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
                                
                                # Add "OOS" tag and record incidents for ONLY the failed products (not moved ones)
                                try:
                                    await client.add_tags_to_order(order["id"], ["OOS"])
                                    logger.info(f"Added OOS tag to order {order.get('name', order['id'])} due to all-or-nothing policy violation")
                                    
                                    # Record OOS incidents for ONLY the products that actually failed to move
                                    _record_oos_incident_for_failed_items(
                                        db=db,
                                        user_id=store.user_id,
                                        store_id=store.id,
                                        order=order,
                                        rule_name=rule.name,
                                        attempted_location_id=location_id,
                                        attempted_location_alias=location_alias,
                                        failed_items=failed_items
                                    )
                                    
                                except Exception as tag_error:
                                    logger.error(f"Failed to add OOS tag for all-or-nothing failure: {str(tag_error)}")
                                
                                # Consider this as complete failure
                                success = False
                                    
                            elif not result["success"]:
                                # Complete failure
                                logger.error(f"Failed to move fulfillment order {fo['id']}: {result.get('errors', [])}")
                                success = False
                                
                                # Log fulfillment error details for reporting
                                _log_order_action(
                                    db, store.user_id, store.id, order["id"], 
                                    order.get("name", "Unknown"), "fulfillment_move_failed", 
                                    "failed", 
                                    {
                                        "rule_name": rule.name,
                                        "target_location_id": location_id,
                                        "fulfillment_order_id": fo["id"],
                                        "location_alias": location_alias or "direct_id",
                                        "errors": result.get("errors", [])
                                    },
                                    error_message="Failed to move fulfillment order - likely out of stock at target location"
                                )
                                
                                # Add "OOS" tag to order for out-of-stock fulfillment issues
                                try:
                                    await client.add_tags_to_order(order["id"], ["OOS"])
                                    logger.info(f"Added OOS tag to order {order.get('name', order['id'])}")
                                    
                                    # Record OOS incident for all products since the entire fulfillment failed
                                    # (we don't have specific info about which products caused the failure)
                                    _record_oos_incident(
                                        db=db,
                                        user_id=store.user_id,
                                        store_id=store.id,
                                        order=order,
                                        rule_name=rule.name,
                                        attempted_location_id=location_id,
                                        attempted_location_alias=location_alias
                                    )
                                    
                                except Exception as tag_error:
                                    logger.error(f"Failed to add OOS tag: {str(tag_error)}")
                                    
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
    error_message: str = None
):
    """Log order processing action"""
    try:
        log_entry = OrderLog(
            user_id=user_id,
            store_id=store_id,
            order_id=order_id,
            order_number=order_number,
            action=action,
            status=status,
            details=details,
            error_message=error_message
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
                    time_since_sync = datetime.utcnow() - store.last_sync
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
def cleanup_old_logs(self):
    """Clean up old order logs and task status records"""
    task_id = self.request.id
    create_task_status(task_id, "cleanup_old_logs", "running")
    
    db = get_db()
    try:
        # Delete logs older than 30 days
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        
        deleted_logs = db.query(OrderLog).filter(
            OrderLog.created_at < cutoff_date
        ).delete()
        
        # Delete task status records older than 7 days
        task_cutoff = datetime.utcnow() - timedelta(days=7)
        deleted_tasks = db.query(TaskStatus).filter(
            TaskStatus.created_at < task_cutoff
        ).delete()
        
        db.commit()
        
        result = {
            "deleted_logs": deleted_logs,
            "deleted_task_records": deleted_tasks,
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
        ).order_by(ProcessingRule.priority.desc()).all()
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
                if rule_engine.evaluate_rule(rule, order_data):
                    rules_applied = True
                    logger.info(f"Rule '{rule.name}' matched! Applying actions...")
                    success = await _apply_rule_actions(client, rule, order_data, store, db)
                    
                    # Log retry attempt
                    _log_order_action(
                        db, user_id, store.id, order_id, 
                        order_data.get("name", "Unknown"), "retry_processing", 
                        "success" if success else "failed",
                        {
                            "retry_type": "specific_rule" if rule_id else "all_rules",
                            "rule_id": rule_id,
                            "rule_name": rule.name,
                            "applied_rule_id": rule.id
                        }
                    )
                else:
                    logger.info(f"Rule '{rule.name}' did not match order {order_data.get('name', 'Unknown')}")
            
            # Log if no rules matched
            if not rules_applied:
                _log_order_action(
                    db, user_id, store.id, order_id,
                    order_data.get("name", "Unknown"), "retry_processing", "info",
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
                db, user_id, 0, order_id, "Unknown", "retry_processing", "failed",
                {"retry_type": "specific_rule" if rule_id else "all_rules", "rule_id": rule_id},
                error_message=str(e)
            )
            failed_count += 1
    
    return {
        "processed_count": processed_count,
        "failed_count": failed_count,
        "total_count": len(order_ids)
    }