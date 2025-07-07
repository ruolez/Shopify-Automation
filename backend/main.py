from fastapi import FastAPI, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date
import uvicorn
import os
import logging
import asyncio
import tempfile
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from database import engine, get_db, create_tables
from models import User, ShopifyStore, ProcessingRule, OrderLog, Settings, ProcessedOrder, LocationAlias, LocationMapping, OutOfStockIncident, ExcludedSKU, AdminUser, AdminAuditLog, SystemSettings
from auth import get_current_user, create_access_token, verify_password, get_password_hash
from admin_auth import get_current_admin_user, create_admin_access_token, verify_admin_password, get_admin_password_hash, log_admin_action, require_admin_role
from schemas import (
    UserCreate, UserLogin, TokenResponse, ShopifyStoreCreate, RuleCreate, SettingsUpdate, SettingsResponse, OrderLogQuery,
    LocationAliasCreate, LocationAliasUpdate, LocationAliasResponse, LocationMappingCreate, LocationMappingUpdate, 
    LocationMappingResponse, StoreLocationResponse, ExcludedSKUCreate, ExcludedSKUUpdate, ExcludedSKUResponse,
    AdminUserCreate, AdminUserLogin, AdminUserUpdate, AdminUserChangePassword, AdminUserResponse, AdminTokenResponse,
    AdminAuditLogResponse, SystemStatsResponse, UserManagementResponse
)
from shopify_client import ShopifyClient
from tasks import test_celery_connection, process_store_orders, process_all_orders
import database_utils
from database_utils import migrate_rules_to_new_format

security = HTTPBearer()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Creating database tables...")
    create_tables()
    print("Database tables created successfully")
    
    # Migrate existing rules to new format
    print("Checking for rule migrations...")
    migrate_rules_to_new_format()
    
    test_celery_connection.delay()
    yield
    # Shutdown
    pass

app = FastAPI(
    title="Shopify Multi-Store Order Management",
    description="Automated order processing and tagging system for multiple Shopify stores",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
# Support environment variable for CORS origins, with fallback to localhost
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost")
if cors_origins:
    cors_origins_list = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
else:
    cors_origins_list = ["http://localhost:3000", "http://localhost"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Shopify Multi-Store Order Management API", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "api"}

# Authentication endpoints
@app.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    # Check if user exists
    db_user = db.query(User).filter(User.email == user_data.email).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    # Create access token
    access_token = create_access_token(data={"sub": db_user.email})
    return TokenResponse(access_token=access_token, token_type="bearer")

@app.post("/auth/login", response_model=TokenResponse)
async def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    access_token = create_access_token(data={"sub": user.email})
    return TokenResponse(access_token=access_token, token_type="bearer")

@app.get("/auth/me")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "created_at": current_user.created_at
    }

# Store management endpoints
@app.post("/stores")
async def add_store(
    store_data: ShopifyStoreCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Test the store connection
    client = ShopifyClient(store_data.shop_domain, store_data.access_token)
    
    try:
        shop_info = await client.get_shop_info()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to connect to Shopify store: {str(e)}"
        )
    
    # Check if store already exists for this user
    existing_store = db.query(ShopifyStore).filter(
        ShopifyStore.shop_domain == store_data.shop_domain,
        ShopifyStore.user_id == current_user.id
    ).first()
    
    if existing_store:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Store already connected"
        )
    
    # Create new store
    db_store = ShopifyStore(
        user_id=current_user.id,
        shop_domain=store_data.shop_domain,
        access_token=store_data.access_token,
        shop_name=shop_info.get("name", store_data.shop_domain),
        is_active=True
    )
    db.add(db_store)
    db.commit()
    db.refresh(db_store)
    
    return {
        "id": db_store.id,
        "shop_domain": db_store.shop_domain,
        "shop_name": db_store.shop_name,
        "is_active": db_store.is_active,
        "created_at": db_store.created_at
    }

@app.get("/stores")
async def get_stores(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    stores = db.query(ShopifyStore).filter(ShopifyStore.user_id == current_user.id).all()
    return [
        {
            "id": store.id,
            "shop_domain": store.shop_domain,
            "shop_name": store.shop_name,
            "is_active": store.is_active,
            "created_at": store.created_at,
            "last_sync": store.last_sync
        }
        for store in stores
    ]

@app.delete("/stores/{store_id}")
async def remove_store(
    store_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()
    
    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found"
        )
    
    db.delete(store)
    db.commit()
    return {"message": "Store removed successfully"}

# Rules management endpoints
@app.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(
    rule_data: RuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Normalize conditions through the schema validator and convert to dict
    # rule_data.conditions is already normalized to dict format by the validator
    if hasattr(rule_data.conditions, 'dict'):
        conditions_to_save = rule_data.conditions.dict()
    else:
        conditions_to_save = rule_data.conditions
    
    db_rule = ProcessingRule(
        user_id=current_user.id,
        name=rule_data.name,
        description=rule_data.description,
        conditions=conditions_to_save,
        actions=[action.dict() for action in rule_data.actions],
        priority=rule_data.priority,
        delay_ms=rule_data.delay_ms,
        is_active=rule_data.is_active
    )
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    
    return {
        "id": db_rule.id,
        "name": db_rule.name,
        "description": db_rule.description,
        "conditions": db_rule.conditions,
        "actions": db_rule.actions,
        "priority": db_rule.priority,
        "delay_ms": db_rule.delay_ms,
        "is_active": db_rule.is_active,
        "created_at": db_rule.created_at
    }

@app.get("/rules")
async def get_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rules = db.query(ProcessingRule).filter(ProcessingRule.user_id == current_user.id).order_by(ProcessingRule.priority.asc()).all()
    return [
        {
            "id": rule.id,
            "name": rule.name,
            "description": rule.description,
            "conditions": rule.conditions,
            "actions": rule.actions,
            "priority": rule.priority,
            "delay_ms": rule.delay_ms,
            "is_active": rule.is_active,
            "created_at": rule.created_at
        }
        for rule in rules
    ]

@app.get("/rules/schema")
async def get_rule_schema(current_user: User = Depends(get_current_user)):
    """Get available fields and operators for rule creation"""
    from rule_engine import RuleEngine
    engine = RuleEngine()
    
    return {
        "fields": engine.get_available_fields(),
        "operators": engine.get_available_operators(),
        "action_types": [
            {"type": "add_tag", "label": "Add Tag", "parameters": ["tags"]},
            {"type": "remove_tag", "label": "Remove Tag", "parameters": ["tags"]},
            {"type": "set_fulfillment_location", "label": "Set Fulfillment Location", "parameters": ["location_id"]}
        ]
    }

@app.get("/rules/{rule_id}")
async def get_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rule = db.query(ProcessingRule).filter(
        ProcessingRule.id == rule_id,
        ProcessingRule.user_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found"
        )
    
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "conditions": rule.conditions,
        "actions": rule.actions,
        "priority": rule.priority,
        "delay_ms": rule.delay_ms,
        "is_active": rule.is_active,
        "created_at": rule.created_at
    }

@app.put("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    rule_data: RuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rule = db.query(ProcessingRule).filter(
        ProcessingRule.id == rule_id,
        ProcessingRule.user_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found"
        )
    
    rule.name = rule_data.name
    rule.description = rule_data.description
    # Normalize conditions through the schema validator and convert to dict
    if hasattr(rule_data.conditions, 'dict'):
        rule.conditions = rule_data.conditions.dict()
    else:
        rule.conditions = rule_data.conditions
    rule.actions = [action.dict() for action in rule_data.actions]
    rule.priority = rule_data.priority
    rule.delay_ms = rule_data.delay_ms
    rule.is_active = rule_data.is_active
    
    db.commit()
    db.refresh(rule)
    
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "conditions": rule.conditions,
        "actions": rule.actions,
        "priority": rule.priority,
        "delay_ms": rule.delay_ms,
        "is_active": rule.is_active,
        "created_at": rule.created_at
    }

@app.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rule = db.query(ProcessingRule).filter(
        ProcessingRule.id == rule_id,
        ProcessingRule.user_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found"
        )
    
    db.delete(rule)
    db.commit()
    return {"message": "Rule deleted successfully"}

@app.put("/rules/bulk/activate")
async def activate_all_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Activate all rules for the current user"""
    rules = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id
    ).all()
    
    activated_count = 0
    for rule in rules:
        if not rule.is_active:
            rule.is_active = True
            activated_count += 1
    
    db.commit()
    return {"message": f"Activated {activated_count} rules", "total_rules": len(rules)}

@app.put("/rules/bulk/deactivate")
async def deactivate_all_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Deactivate all rules for the current user"""
    rules = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id
    ).all()
    
    deactivated_count = 0
    for rule in rules:
        if rule.is_active:
            rule.is_active = False
            deactivated_count += 1
    
    db.commit()
    return {"message": f"Deactivated {deactivated_count} rules", "total_rules": len(rules)}

@app.get("/stores/{store_id}/locations")
async def get_store_locations(
    store_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()
    
    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found"
        )
    
    try:
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        # Run async operation
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            locations = loop.run_until_complete(client.get_locations())
            return locations
        finally:
            loop.close()
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch locations: {str(e)}"
        )

# Dashboard endpoints
@app.get("/dashboard/stats")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Get user's stores
    stores_count = db.query(ShopifyStore).filter(ShopifyStore.user_id == current_user.id).count()
    active_stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id,
        ShopifyStore.is_active == True
    ).count()
    
    # Get rules count
    rules_count = db.query(ProcessingRule).filter(ProcessingRule.user_id == current_user.id).count()
    active_rules = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id,
        ProcessingRule.is_active == True
    ).count()
    
    # Get recent order processing logs
    recent_logs = db.query(OrderLog).filter(
        OrderLog.user_id == current_user.id
    ).order_by(OrderLog.created_at.desc()).limit(10).all()
    
    return {
        "stores": {
            "total": stores_count,
            "active": active_stores
        },
        "rules": {
            "total": rules_count,
            "active": active_rules
        },
        "recent_activity": [
            {
                "id": log.id,
                "order_number": log.order_number,
                "action": log.action,
                "status": log.status,
                "created_at": log.created_at
            }
            for log in recent_logs
        ]
    }

# Locations endpoint
@app.get("/locations")
async def get_all_locations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all locations from all connected stores"""
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id,
        ShopifyStore.is_active == True
    ).all()
    
    all_locations = []
    
    for store in stores:
        try:
            client = ShopifyClient(store.shop_domain, store.access_token)
            locations = await client.get_locations()
            
            for location in locations:
                all_locations.append({
                    "id": location["id"],
                    "name": location["name"],
                    "store_name": store.shop_name,
                    "store_domain": store.shop_domain,
                    "store_id": store.id,
                    "is_active": location.get("active", True),
                    "address": location.get("address", {})
                })
                
        except Exception as e:
            logger.error(f"Error fetching locations for store {store.shop_domain}: {str(e)}")
            continue
    
    return {"locations": all_locations}

# Settings endpoints
@app.get("/settings", response_model=SettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
    
    # Create default settings if none exist
    if not settings:
        settings = Settings(user_id=current_user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    print(f"DEBUG: GET settings for user {current_user.id} - timezone: {settings.timezone}, date_format: {settings.date_format}")
    return settings

@app.put("/settings", response_model=SettingsResponse)
async def update_settings(
    settings_data: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
    
    if not settings:
        settings = Settings(user_id=current_user.id)
        db.add(settings)
    
    # Update only provided fields
    update_data = settings_data.dict(exclude_unset=True)
    print(f"DEBUG: Updating settings for user {current_user.id}: {update_data}")
    
    for field, value in update_data.items():
        if value is not None:
            setattr(settings, field, value)
            print(f"DEBUG: Set {field} = {value}")
    
    db.commit()
    db.refresh(settings)
    print(f"DEBUG: Settings after update - timezone: {settings.timezone}, date_format: {settings.date_format}")
    return settings

@app.post("/settings/reset-data")
async def reset_user_data(
    reset_options: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reset user data while preserving configuration"""
    # Validate confirmation
    confirmation_text = reset_options.get("confirmation", "")
    if confirmation_text != "RESET":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid confirmation. Please type 'RESET' to confirm."
        )
    
    # Get options
    reset_order_logs = reset_options.get("reset_order_logs", True)
    reset_processed_orders = reset_options.get("reset_processed_orders", True)
    reset_oos_incidents = reset_options.get("reset_oos_incidents", True)
    reset_task_status = reset_options.get("reset_task_status", False)
    
    deleted_counts = {}
    
    try:
        # Delete order logs
        if reset_order_logs:
            count = db.query(OrderLog).filter(OrderLog.user_id == current_user.id).count()
            db.query(OrderLog).filter(OrderLog.user_id == current_user.id).delete()
            deleted_counts["order_logs"] = count
            logger.info(f"Deleted {count} order logs for user {current_user.id}")
        
        # Delete processed orders (allows reprocessing)
        if reset_processed_orders:
            # Get user's store IDs
            store_ids = db.query(ShopifyStore.id).filter(
                ShopifyStore.user_id == current_user.id
            ).all()
            store_ids = [s[0] for s in store_ids]
            
            count = db.query(ProcessedOrder).filter(
                ProcessedOrder.store_id.in_(store_ids)
            ).count()
            db.query(ProcessedOrder).filter(
                ProcessedOrder.store_id.in_(store_ids)
            ).delete(synchronize_session=False)
            deleted_counts["processed_orders"] = count
            logger.info(f"Deleted {count} processed orders for user {current_user.id}")
        
        # Delete OOS incidents
        if reset_oos_incidents:
            count = db.query(OutOfStockIncident).filter(
                OutOfStockIncident.user_id == current_user.id
            ).count()
            db.query(OutOfStockIncident).filter(
                OutOfStockIncident.user_id == current_user.id
            ).delete()
            deleted_counts["oos_incidents"] = count
            logger.info(f"Deleted {count} OOS incidents for user {current_user.id}")
        
        # Delete old task status records (optional)
        if reset_task_status:
            # Only delete completed tasks older than 1 day
            cutoff_date = datetime.utcnow() - timedelta(days=1)
            count = db.query(TaskStatus).filter(
                TaskStatus.completed_at < cutoff_date,
                TaskStatus.status.in_(["success", "failed"])
            ).count()
            db.query(TaskStatus).filter(
                TaskStatus.completed_at < cutoff_date,
                TaskStatus.status.in_(["success", "failed"])
            ).delete()
            deleted_counts["task_status"] = count
            logger.info(f"Deleted {count} old task status records")
        
        # Commit all deletions
        db.commit()
        
        # Log the reset action
        reset_log = OrderLog(
            user_id=current_user.id,
            store_id=0,  # System action, no specific store
            order_id="SYSTEM_RESET",
            order_number="SYSTEM",
            action="data_reset",
            status="success",
            details={
                "deleted_counts": deleted_counts,
                "options": {
                    "reset_order_logs": reset_order_logs,
                    "reset_processed_orders": reset_processed_orders,
                    "reset_oos_incidents": reset_oos_incidents,
                    "reset_task_status": reset_task_status
                }
            }
        )
        db.add(reset_log)
        db.commit()
        
        return {
            "message": "Data reset completed successfully",
            "deleted_counts": deleted_counts,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Data reset failed for user {current_user.id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset data: {str(e)}"
        )

@app.get("/settings/data-stats")
async def get_data_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get statistics about user's data for reset confirmation"""
    # Get user's store IDs
    store_ids = db.query(ShopifyStore.id).filter(
        ShopifyStore.user_id == current_user.id
    ).all()
    store_ids = [s[0] for s in store_ids]
    
    stats = {
        "order_logs": db.query(OrderLog).filter(OrderLog.user_id == current_user.id).count(),
        "processed_orders": db.query(ProcessedOrder).filter(
            ProcessedOrder.store_id.in_(store_ids)
        ).count() if store_ids else 0,
        "oos_incidents": db.query(OutOfStockIncident).filter(
            OutOfStockIncident.user_id == current_user.id
        ).count(),
        "task_status": db.query(TaskStatus).filter(
            TaskStatus.completed_at < datetime.utcnow() - timedelta(days=1),
            TaskStatus.status.in_(["success", "failed"])
        ).count()
    }
    
    return stats

@app.get("/settings/timezones")
async def get_timezones(
    current_user: User = Depends(get_current_user)
):
    """Get list of available timezones"""
    import pytz
    
    # Group timezones by region for better UX
    timezone_groups = {
        "Common": [
            "UTC",
            "US/Eastern",
            "US/Central",
            "US/Mountain",
            "US/Pacific",
            "Europe/London",
            "Europe/Paris",
            "Asia/Tokyo",
            "Asia/Shanghai",
            "Australia/Sydney"
        ],
        "Americas": [],
        "Europe": [],
        "Asia": [],
        "Africa": [],
        "Australia": [],
        "Pacific": [],
        "Other": []
    }
    
    # Categorize all timezones
    for tz in pytz.all_timezones:
        if tz in timezone_groups["Common"]:
            continue
            
        if tz.startswith("US/") or tz.startswith("America/") or tz.startswith("Canada/"):
            timezone_groups["Americas"].append(tz)
        elif tz.startswith("Europe/"):
            timezone_groups["Europe"].append(tz)
        elif tz.startswith("Asia/"):
            timezone_groups["Asia"].append(tz)
        elif tz.startswith("Africa/"):
            timezone_groups["Africa"].append(tz)
        elif tz.startswith("Australia/"):
            timezone_groups["Australia"].append(tz)
        elif tz.startswith("Pacific/"):
            timezone_groups["Pacific"].append(tz)
        else:
            timezone_groups["Other"].append(tz)
    
    # Sort timezones within each group
    for group in timezone_groups:
        if group != "Common":  # Keep Common in predefined order
            timezone_groups[group].sort()
    
    return {
        "groups": timezone_groups,
        "all": pytz.all_timezones
    }

@app.get("/settings/date-formats")
async def get_date_formats(
    current_user: User = Depends(get_current_user)
):
    """Get list of available date formats with examples"""
    from datetime import datetime
    import pytz
    
    # Sample date for examples
    sample_date = datetime(2024, 3, 15, 14, 30, 45)
    
    formats = [
        {
            "format": "MMM d, yyyy HH:mm",
            "description": "Default format",
            "example": "Mar 15, 2024 14:30"
        },
        {
            "format": "MM/dd/yyyy HH:mm:ss",
            "description": "US format with seconds",
            "example": "03/15/2024 14:30:45"
        },
        {
            "format": "dd/MM/yyyy HH:mm",
            "description": "European format",
            "example": "15/03/2024 14:30"
        },
        {
            "format": "yyyy-MM-dd HH:mm:ss",
            "description": "ISO format",
            "example": "2024-03-15 14:30:45"
        },
        {
            "format": "d MMM yyyy, h:mm a",
            "description": "12-hour format",
            "example": "15 Mar 2024, 2:30 PM"
        },
        {
            "format": "EEEE, MMMM d, yyyy",
            "description": "Full date only",
            "example": "Friday, March 15, 2024"
        },
        {
            "format": "MMM d, h:mm a",
            "description": "Short format with 12-hour time",
            "example": "Mar 15, 2:30 PM"
        },
        {
            "format": "yyyy-MM-dd'T'HH:mm:ss",
            "description": "ISO 8601 format",
            "example": "2024-03-15T14:30:45"
        }
    ]
    
    return formats

# Order logs endpoints
@app.get("/order-logs")
async def get_order_logs(
    store_id: Optional[int] = None,
    status: Optional[str] = None,
    action: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(OrderLog).filter(OrderLog.user_id == current_user.id)
    
    if store_id:
        query = query.filter(OrderLog.store_id == store_id)
    if status:
        query = query.filter(OrderLog.status == status)
    if action:
        query = query.filter(OrderLog.action.contains(action))
    
    # Get total count
    total = query.count()
    
    # Paginate
    offset = (page - 1) * per_page
    logs = query.order_by(OrderLog.created_at.desc()).offset(offset).limit(per_page).all()
    
    # Get store names
    store_ids = list(set(log.store_id for log in logs))
    stores = db.query(ShopifyStore).filter(ShopifyStore.id.in_(store_ids)).all()
    store_map = {store.id: store.shop_name for store in stores}
    
    return {
        "logs": [
            {
                "id": log.id,
                "store_id": log.store_id,
                "store_name": store_map.get(log.store_id, "Unknown"),
                "order_id": log.order_id,
                "order_number": log.order_number,
                "action": log.action,
                "status": log.status,
                "details": log.details,
                "error_message": log.error_message,
                "created_at": log.created_at.isoformat() + 'Z' if log.created_at else None
            }
            for log in logs
        ],
        "pagination": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page
        }
    }

@app.post("/order-logs/retry")
async def retry_order_processing_endpoint(
    retry_request: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retry processing for selected orders"""
    from tasks import retry_order_processing
    
    order_ids = retry_request.get("order_ids", [])
    rule_id = retry_request.get("rule_id")  # Optional - if not provided, retry with all rules
    
    if not order_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No order IDs provided"
        )
    
    if len(order_ids) > 50:  # Limit batch size
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many orders selected. Maximum 50 orders at once."
        )
    
    # Validate rule_id if provided
    if rule_id:
        rule = db.query(ProcessingRule).filter(
            ProcessingRule.id == rule_id,
            ProcessingRule.user_id == current_user.id,
            ProcessingRule.is_active == True
        ).first()
        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rule not found or inactive"
            )
    
    try:
        # Run async retry processing using await (FastAPI already has event loop)
        result = await retry_order_processing(order_ids, rule_id, current_user.id, db)
        
        return {
            "message": "Order retry processing completed",
            "processed_count": result["processed_count"],
            "failed_count": result["failed_count"],
            "total_count": result["total_count"],
            "retry_type": "specific_rule" if rule_id else "all_rules",
            "rule_id": rule_id
        }
            
    except Exception as e:
        logger.error(f"Order retry processing failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retry order processing: {str(e)}"
        )

# Manual sync endpoints
@app.post("/sync/store/{store_id}")
async def sync_store_orders(
    store_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify store ownership
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()
    
    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found"
        )
    
    # Queue sync task
    task = process_store_orders.delay(current_user.id, store_id)
    
    return {
        "message": "Sync task queued",
        "task_id": task.id,
        "store_name": store.shop_name
    }

@app.post("/sync/all")
async def sync_all_stores(
    current_user: User = Depends(get_current_user)
):
    # Queue sync all task
    task = process_all_orders.delay()
    
    return {
        "message": "Sync all stores task queued",
        "task_id": task.id
    }

# === DEBUGGING ENDPOINTS ===

@app.get("/debug/locations/{store_id}")
async def debug_get_locations(
    store_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all available locations for a store"""
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    try:
        client = ShopifyClient(store.shop_domain, store.access_token)
        locations = await client.get_locations()
        
        return {
            "store": store.shop_name,
            "locations": locations,
            "count": len(locations)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching locations: {str(e)}")

@app.get("/debug/orders/{store_id}")
async def debug_get_recent_orders(
    store_id: int,
    limit: int = 3,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get recent orders with fulfillment details"""
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    try:
        client = ShopifyClient(store.shop_domain, store.access_token)
        orders_data = await client.get_orders(limit=limit)
        
        debug_orders = []
        for order_edge in orders_data["edges"]:
            order = order_edge["node"]
            
            # Extract fulfillment order details
            fulfillment_orders = []
            for fo_edge in order.get("fulfillmentOrders", {}).get("edges", []):
                fo = fo_edge["node"]
                assigned_location = fo.get("assignedLocation", {}).get("location", {})
                
                fulfillment_orders.append({
                    "id": fo["id"],
                    "status": fo["status"],
                    "can_move": fo["status"] in ["open", "scheduled"],
                    "current_location": {
                        "id": assigned_location.get("id"),
                        "name": assigned_location.get("name")
                    }
                })
            
            debug_orders.append({
                "id": order["id"],
                "name": order["name"],
                "created_at": order["createdAt"],
                "total": order.get("totalPriceSet", {}).get("shopMoney", {}).get("amount", "0"),
                "tags": order.get("tags", []),
                "fulfillment_orders": fulfillment_orders,
                "fulfillment_orders_count": len(fulfillment_orders)
            })
        
        return {
            "store": store.shop_name,
            "orders": debug_orders
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching orders: {str(e)}")

@app.get("/debug/rules/{rule_id}")
async def debug_get_rule_details(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed rule information"""
    rule = db.query(ProcessingRule).filter(
        ProcessingRule.id == rule_id,
        ProcessingRule.user_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # Check for fulfillment actions
    fulfillment_actions = []
    for action in rule.actions:
        if action.get("type") == "set_fulfillment_location":
            fulfillment_actions.append(action)
    
    return {
        "rule": {
            "id": rule.id,
            "name": rule.name,
            "is_active": rule.is_active,
            "conditions": rule.conditions,
            "actions": rule.actions,
            "fulfillment_actions": fulfillment_actions,
            "has_fulfillment_actions": len(fulfillment_actions) > 0
        }
    }

@app.post("/debug/test-rule/{rule_id}/{store_id}")
async def debug_test_rule_on_order(
    rule_id: int,
    store_id: int,
    order_name: str,  # e.g., "TS1395"
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Test a specific rule against a specific order"""
    # Get rule
    rule = db.query(ProcessingRule).filter(
        ProcessingRule.id == rule_id,
        ProcessingRule.user_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # Get store
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    try:
        from rule_engine import RuleEngine
        
        client = ShopifyClient(store.shop_domain, store.access_token)
        rule_engine = RuleEngine()
        
        # Get orders and find the specific one
        orders_data = await client.get_orders(limit=50)
        target_order = None
        
        for order_edge in orders_data["edges"]:
            order = order_edge["node"]
            if order["name"] == order_name:
                target_order = order
                break
        
        if not target_order:
            return {"error": f"Order {order_name} not found"}
        
        # Test rule evaluation
        rule_matches = rule_engine.evaluate_rule(rule, target_order)
        
        # Get fulfillment details
        fulfillment_orders = target_order.get("fulfillmentOrders", {}).get("edges", [])
        fulfillment_details = []
        
        for fo_edge in fulfillment_orders:
            fo = fo_edge["node"]
            assigned_location = fo.get("assignedLocation", {}).get("location", {})
            fulfillment_details.append({
                "id": fo["id"],
                "status": fo["status"],
                "can_move": fo["status"] in ["open", "scheduled"],
                "current_location": assigned_location
            })
        
        # Check fulfillment actions in rule
        fulfillment_actions = [a for a in rule.actions if a.get("type") == "set_fulfillment_location"]
        
        return {
            "order": {
                "id": target_order["id"],
                "name": target_order["name"],
                "tags": target_order.get("tags", [])
            },
            "rule": {
                "id": rule.id,
                "name": rule.name,
                "matches_order": rule_matches
            },
            "fulfillment": {
                "orders": fulfillment_details,
                "count": len(fulfillment_details),
                "moveable_count": len([f for f in fulfillment_details if f["can_move"]])
            },
            "actions": {
                "total": len(rule.actions),
                "fulfillment_actions": fulfillment_actions,
                "fulfillment_count": len(fulfillment_actions)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing rule: {str(e)}")

@app.post("/debug/move-fulfillment")
async def debug_move_fulfillment(
    store_id: int,
    order_name: str,
    location_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually test moving fulfillment location"""
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    try:
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        # Find the order
        orders_data = await client.get_orders(limit=50)
        target_order = None
        
        for order_edge in orders_data["edges"]:
            order = order_edge["node"]
            if order["name"] == order_name:
                target_order = order
                break
        
        if not target_order:
            return {"error": f"Order {order_name} not found"}
        
        # Try to move fulfillment orders
        fulfillment_orders = target_order.get("fulfillmentOrders", {}).get("edges", [])
        results = []
        
        for fo_edge in fulfillment_orders:
            fo = fo_edge["node"]
            
            if fo["status"] in ["open", "scheduled"]:
                try:
                    result = await client.move_fulfillment_order(fo["id"], location_id)
                    results.append({
                        "fulfillment_order_id": fo["id"],
                        "success": result,
                        "status": fo["status"]
                    })
                except Exception as e:
                    results.append({
                        "fulfillment_order_id": fo["id"],
                        "success": False,
                        "error": str(e),
                        "status": fo["status"]
                    })
            else:
                results.append({
                    "fulfillment_order_id": fo["id"],
                    "success": False,
                    "error": f"Cannot move fulfillment order with status: {fo['status']}",
                    "status": fo["status"]
                })
        
        return {
            "order_name": order_name,
            "location_id": location_id,
            "fulfillment_orders_processed": len(results),
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error moving fulfillment: {str(e)}")

@app.get("/debug/order-data/{store_id}")
async def debug_order_data(
    store_id: int,
    order_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug endpoint to show raw order data structure"""
    try:
        # Get store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == current_user.id,
            ShopifyStore.is_active == True
        ).first()
        
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        # Find order by name
        orders_data = await client.get_orders(limit=50)
        target_order = None
        
        for order_edge in orders_data["edges"]:
            order = order_edge["node"]
            if order["name"] == order_name:
                target_order = order
                break
        
        if not target_order:
            return {"error": f"Order {order_name} not found"}
        
        # Extract weight information
        weight_info = {
            "order_name": target_order.get("name"),
            "currentTotalWeight": target_order.get("currentTotalWeight"),
            "currentTotalWeight_type": type(target_order.get("currentTotalWeight")).__name__,
            "totalWeight": target_order.get("totalWeight"),  # Check if this field exists
        }
        
        # Also show line item weights
        line_items = target_order.get("lineItems", {}).get("edges", [])
        item_weights = []
        for item_edge in line_items:
            item = item_edge["node"]
            variant = item.get("variant", {})
            inventory_item = variant.get("inventoryItem", {})
            measurement = inventory_item.get("measurement", {})
            weight = measurement.get("weight", {})
            
            item_weights.append({
                "title": item.get("title"),
                "quantity": item.get("quantity"),
                "weight_value": weight.get("value"),
                "weight_unit": weight.get("unit")
            })
        
        return {
            "weight_info": weight_info,
            "line_item_weights": item_weights,
            "full_order_data": target_order
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting order data: {str(e)}")

# Location Alias Management endpoints
@app.get("/location-aliases", response_model=list[LocationAliasResponse])
async def get_location_aliases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all location aliases for the current user"""
    aliases = db.query(LocationAlias).filter(
        LocationAlias.user_id == current_user.id
    ).order_by(LocationAlias.alias_name).all()
    
    # Build response with mappings
    result = []
    for alias in aliases:
        mappings = []
        for mapping in alias.mappings:
            mappings.append(LocationMappingResponse(
                id=mapping.id,
                store_id=mapping.store_id,
                store_name=mapping.store.shop_name,
                store_domain=mapping.store.shop_domain,
                shopify_location_id=mapping.shopify_location_id,
                shopify_location_name=mapping.shopify_location_name,
                is_active=mapping.is_active,
                created_at=mapping.created_at
            ))
        
        result.append(LocationAliasResponse(
            id=alias.id,
            alias_name=alias.alias_name,
            description=alias.description,
            is_active=alias.is_active,
            created_at=alias.created_at,
            updated_at=alias.updated_at,
            mappings=mappings
        ))
    
    return result

@app.post("/location-aliases", response_model=LocationAliasResponse)
async def create_location_alias(
    alias_data: LocationAliasCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new location alias"""
    # Check if alias name already exists for this user
    existing = db.query(LocationAlias).filter(
        LocationAlias.user_id == current_user.id,
        LocationAlias.alias_name == alias_data.alias_name
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400, 
            detail=f"Location alias '{alias_data.alias_name}' already exists"
        )
    
    alias = LocationAlias(
        user_id=current_user.id,
        alias_name=alias_data.alias_name,
        description=alias_data.description
    )
    
    db.add(alias)
    db.commit()
    db.refresh(alias)
    
    return LocationAliasResponse(
        id=alias.id,
        alias_name=alias.alias_name,
        description=alias.description,
        is_active=alias.is_active,
        created_at=alias.created_at,
        updated_at=alias.updated_at,
        mappings=[]
    )

@app.put("/location-aliases/{alias_id}", response_model=LocationAliasResponse)
async def update_location_alias(
    alias_id: int,
    alias_data: LocationAliasUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a location alias"""
    alias = db.query(LocationAlias).filter(
        LocationAlias.id == alias_id,
        LocationAlias.user_id == current_user.id
    ).first()
    
    if not alias:
        raise HTTPException(status_code=404, detail="Location alias not found")
    
    # Check for name conflicts if name is being changed
    if alias_data.alias_name and alias_data.alias_name != alias.alias_name:
        existing = db.query(LocationAlias).filter(
            LocationAlias.user_id == current_user.id,
            LocationAlias.alias_name == alias_data.alias_name,
            LocationAlias.id != alias_id
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=400, 
                detail=f"Location alias '{alias_data.alias_name}' already exists"
            )
    
    # Update fields
    if alias_data.alias_name is not None:
        alias.alias_name = alias_data.alias_name
    if alias_data.description is not None:
        alias.description = alias_data.description
    if alias_data.is_active is not None:
        alias.is_active = alias_data.is_active
    
    db.commit()
    db.refresh(alias)
    
    # Build response with mappings
    mappings = []
    for mapping in alias.mappings:
        mappings.append(LocationMappingResponse(
            id=mapping.id,
            store_id=mapping.store_id,
            store_name=mapping.store.shop_name,
            store_domain=mapping.store.shop_domain,
            shopify_location_id=mapping.shopify_location_id,
            shopify_location_name=mapping.shopify_location_name,
            is_active=mapping.is_active,
            created_at=mapping.created_at
        ))
    
    return LocationAliasResponse(
        id=alias.id,
        alias_name=alias.alias_name,
        description=alias.description,
        is_active=alias.is_active,
        created_at=alias.created_at,
        updated_at=alias.updated_at,
        mappings=mappings
    )

@app.delete("/location-aliases/{alias_id}")
async def delete_location_alias(
    alias_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a location alias and all its mappings"""
    alias = db.query(LocationAlias).filter(
        LocationAlias.id == alias_id,
        LocationAlias.user_id == current_user.id
    ).first()
    
    if not alias:
        raise HTTPException(status_code=404, detail="Location alias not found")
    
    db.delete(alias)
    db.commit()
    
    return {"message": f"Location alias '{alias.alias_name}' deleted successfully"}

# Location Mapping endpoints
@app.get("/location-aliases/{alias_id}/mappings", response_model=list[LocationMappingResponse])
async def get_alias_mappings(
    alias_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all mappings for a specific alias"""
    alias = db.query(LocationAlias).filter(
        LocationAlias.id == alias_id,
        LocationAlias.user_id == current_user.id
    ).first()
    
    if not alias:
        raise HTTPException(status_code=404, detail="Location alias not found")
    
    mappings = []
    for mapping in alias.mappings:
        mappings.append(LocationMappingResponse(
            id=mapping.id,
            store_id=mapping.store_id,
            store_name=mapping.store.shop_name,
            store_domain=mapping.store.shop_domain,
            shopify_location_id=mapping.shopify_location_id,
            shopify_location_name=mapping.shopify_location_name,
            is_active=mapping.is_active,
            created_at=mapping.created_at
        ))
    
    return mappings

@app.post("/location-aliases/{alias_id}/mappings", response_model=LocationMappingResponse)
async def create_alias_mapping(
    alias_id: int,
    mapping_data: LocationMappingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create or update a mapping for an alias to a store location"""
    alias = db.query(LocationAlias).filter(
        LocationAlias.id == alias_id,
        LocationAlias.user_id == current_user.id
    ).first()
    
    if not alias:
        raise HTTPException(status_code=404, detail="Location alias not found")
    
    # Verify store belongs to user
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == mapping_data.store_id,
        ShopifyStore.user_id == current_user.id
    ).first()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # Check if mapping already exists
    existing_mapping = db.query(LocationMapping).filter(
        LocationMapping.alias_id == alias_id,
        LocationMapping.store_id == mapping_data.store_id
    ).first()
    
    if existing_mapping:
        # Update existing mapping
        existing_mapping.shopify_location_id = mapping_data.shopify_location_id
        existing_mapping.shopify_location_name = mapping_data.shopify_location_name
        existing_mapping.is_active = True
        db.commit()
        db.refresh(existing_mapping)
        mapping = existing_mapping
    else:
        # Create new mapping
        mapping = LocationMapping(
            alias_id=alias_id,
            store_id=mapping_data.store_id,
            shopify_location_id=mapping_data.shopify_location_id,
            shopify_location_name=mapping_data.shopify_location_name
        )
        db.add(mapping)
        db.commit()
        db.refresh(mapping)
    
    return LocationMappingResponse(
        id=mapping.id,
        store_id=mapping.store_id,
        store_name=store.shop_name,
        store_domain=store.shop_domain,
        shopify_location_id=mapping.shopify_location_id,
        shopify_location_name=mapping.shopify_location_name,
        is_active=mapping.is_active,
        created_at=mapping.created_at
    )

@app.delete("/location-mappings/{mapping_id}")
async def delete_location_mapping(
    mapping_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a specific location mapping"""
    mapping = db.query(LocationMapping).join(LocationAlias).filter(
        LocationMapping.id == mapping_id,
        LocationAlias.user_id == current_user.id
    ).first()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="Location mapping not found")
    
    db.delete(mapping)
    db.commit()
    
    return {"message": "Location mapping deleted successfully"}

# Store locations helper endpoint
@app.get("/store-locations", response_model=list[StoreLocationResponse])
async def get_store_locations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get available locations from all user's stores"""
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id,
        ShopifyStore.is_active == True
    ).all()
    
    result = []
    for store in stores:
        try:
            client = ShopifyClient(store.shop_domain, store.access_token)
            locations = await client.get_locations()
            
            location_list = []
            for location in locations:
                location_list.append({
                    "id": location["id"],
                    "name": location["name"]
                })
            
            result.append(StoreLocationResponse(
                store_id=store.id,
                store_name=store.shop_name,
                store_domain=store.shop_domain,
                locations=location_list
            ))
        except Exception as e:
            logger.error(f"Error fetching locations for store {store.shop_domain}: {str(e)}")
            # Include store even if location fetch fails
            result.append(StoreLocationResponse(
                store_id=store.id,
                store_name=store.shop_name,
                store_domain=store.shop_domain,
                locations=[]
            ))
    
    return result

# Reports endpoints
@app.get("/reports/fulfillment-errors")
async def get_fulfillment_error_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get fulfillment error report with optional date filtering"""
    try:
        # Build query for fulfillment errors
        query = db.query(OrderLog).filter(
            OrderLog.user_id == current_user.id,
            OrderLog.action == "fulfillment_move_failed"
        )
        
        # Apply date filters if provided
        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            query = query.filter(OrderLog.created_at >= start_dt)
        
        if end_date:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            query = query.filter(OrderLog.created_at <= end_dt)
        
        # Get the error logs
        error_logs = query.order_by(OrderLog.created_at.desc()).all()
        
        # Process the data to extract product information
        product_errors = {}
        location_errors = {}
        
        for log in error_logs:
            details = log.details or {}
            location_alias = details.get("location_alias", "unknown")
            target_location = details.get("target_location_id", "unknown")
            
            # Track errors by location
            if location_alias not in location_errors:
                location_errors[location_alias] = {
                    "location_alias": location_alias,
                    "target_location_id": target_location,
                    "error_count": 0,
                    "orders": []
                }
            
            location_errors[location_alias]["error_count"] += 1
            location_errors[location_alias]["orders"].append({
                "order_number": log.order_number,
                "created_at": log.created_at.isoformat(),
                "rule_name": details.get("rule_name", "unknown")
            })
        
        return {
            "total_errors": len(error_logs),
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            },
            "location_errors": list(location_errors.values()),
            "detailed_logs": [
                {
                    "id": log.id,
                    "order_number": log.order_number,
                    "created_at": log.created_at.isoformat(),
                    "rule_name": log.details.get("rule_name") if log.details else None,
                    "location_alias": log.details.get("location_alias") if log.details else None,
                    "target_location_id": log.details.get("target_location_id") if log.details else None,
                    "error_message": log.error_message
                }
                for log in error_logs
            ]
        }
        
    except Exception as e:
        logger.error(f"Error generating fulfillment error report: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate report")

@app.get("/reports/oos-orders")
async def get_oos_orders_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get orders tagged with OOS (Out of Stock) during the specified period"""
    try:
        # Get orders that failed fulfillment moves (complete or partial) and should have OOS tags
        query = db.query(OrderLog).filter(
            OrderLog.user_id == current_user.id,
            OrderLog.action.in_(["fulfillment_move_failed", "fulfillment_partial_move"])
        )
        
        # Apply date filters
        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            query = query.filter(OrderLog.created_at >= start_dt)
        
        if end_date:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            query = query.filter(OrderLog.created_at <= end_dt)
        
        oos_logs = query.order_by(OrderLog.created_at.desc()).all()
        
        # Deduplicate orders by order_number - keep most recent entry for each order
        unique_orders = {}
        for log in oos_logs:
            order_number = log.order_number
            if order_number not in unique_orders or log.created_at > unique_orders[order_number].created_at:
                unique_orders[order_number] = log
        
        # Convert back to list, sorted by creation date descending
        deduplicated_logs = sorted(unique_orders.values(), key=lambda x: x.created_at, reverse=True)
        
        # Group by location for summary using deduplicated data
        location_summary = {}
        for log in deduplicated_logs:
            details = log.details or {}
            location_alias = details.get("location_alias", "unknown")
            
            if location_alias not in location_summary:
                location_summary[location_alias] = {
                    "location_alias": location_alias,
                    "order_count": 0,
                    "orders": []
                }
            
            location_summary[location_alias]["order_count"] += 1
            location_summary[location_alias]["orders"].append({
                "order_number": log.order_number,
                "created_at": log.created_at.isoformat()
            })
        
        return {
            "total_oos_orders": len(deduplicated_logs),
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            },
            "location_summary": list(location_summary.values()),
            "orders": [
                {
                    "order_number": log.order_number,
                    "created_at": log.created_at.isoformat(),
                    "location_alias": log.details.get("location_alias") if log.details else None,
                    "rule_name": log.details.get("rule_name") if log.details else None
                }
                for log in deduplicated_logs
            ]
        }
        
    except Exception as e:
        logger.error(f"Error generating OOS orders report: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate OOS report")

@app.get("/reports/oos-products")
async def get_oos_products_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get product-grouped out-of-stock incidents report"""
    try:
        from sqlalchemy import func, desc
        
        # Build base query for OOS incidents
        query = db.query(OutOfStockIncident).filter(
            OutOfStockIncident.user_id == current_user.id
        )
        
        # Apply date filters
        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            query = query.filter(OutOfStockIncident.incident_date >= start_dt)
        
        if end_date:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            query = query.filter(OutOfStockIncident.incident_date <= end_dt)
        
        # Get aggregated product data with deduplication
        product_aggregates = db.query(
            OutOfStockIncident.product_id,
            OutOfStockIncident.variant_id,
            OutOfStockIncident.product_title,
            OutOfStockIncident.variant_title,
            OutOfStockIncident.sku,
            OutOfStockIncident.vendor,
            OutOfStockIncident.product_type,
            func.count(func.distinct(func.concat(OutOfStockIncident.order_id, '|', OutOfStockIncident.rule_name, '|', OutOfStockIncident.attempted_location_id))).label('unique_incidents'),
            func.count(OutOfStockIncident.id).label('total_records'),
            func.sum(OutOfStockIncident.quantity_attempted).label('total_quantity_affected'),
            func.count(func.distinct(OutOfStockIncident.order_id)).label('affected_orders'),
            func.min(OutOfStockIncident.incident_date).label('first_incident'),
            func.max(OutOfStockIncident.incident_date).label('last_incident')
        ).filter(
            OutOfStockIncident.user_id == current_user.id
        )
        
        # Apply same date filters to aggregation
        if start_date:
            product_aggregates = product_aggregates.filter(OutOfStockIncident.incident_date >= start_dt)
        if end_date:
            product_aggregates = product_aggregates.filter(OutOfStockIncident.incident_date <= end_dt)
        
        # Group by product and variant
        product_aggregates = product_aggregates.group_by(
            OutOfStockIncident.product_id,
            OutOfStockIncident.variant_id,
            OutOfStockIncident.product_title,
            OutOfStockIncident.variant_title,
            OutOfStockIncident.sku,
            OutOfStockIncident.vendor,
            OutOfStockIncident.product_type
        ).order_by(desc('unique_incidents')).all()
        
        # Get total counts
        total_incidents = query.count()
        unique_products = len(product_aggregates)
        
        # Format product data
        products = []
        for product in product_aggregates:
            # Get affected locations for this product
            locations_query = db.query(
                func.distinct(OutOfStockIncident.attempted_location_alias)
            ).filter(
                OutOfStockIncident.user_id == current_user.id,
                OutOfStockIncident.product_id == product.product_id,
                OutOfStockIncident.variant_id == product.variant_id
            )
            
            if start_date:
                locations_query = locations_query.filter(OutOfStockIncident.incident_date >= start_dt)
            if end_date:
                locations_query = locations_query.filter(OutOfStockIncident.incident_date <= end_dt)
                
            locations_affected = [loc[0] for loc in locations_query.all() if loc[0]]
            
            # Calculate incident frequency (incidents per day)
            if product.first_incident and product.last_incident:
                days_span = max(1, (product.last_incident - product.first_incident).days + 1)
                incident_frequency = round(product.unique_incidents / days_span, 2)
            else:
                incident_frequency = 0
            
            products.append({
                "product_id": product.product_id,
                "variant_id": product.variant_id,
                "product_title": product.product_title,
                "variant_title": product.variant_title or "",
                "sku": product.sku or "",
                "vendor": product.vendor or "",
                "product_type": product.product_type or "",
                "unique_incidents": product.unique_incidents,
                "total_records": product.total_records,
                "total_quantity_affected": product.total_quantity_affected,
                "affected_orders": product.affected_orders,
                "locations_affected": locations_affected,
                "first_incident": product.first_incident.isoformat() if product.first_incident else None,
                "last_incident": product.last_incident.isoformat() if product.last_incident else None,
                "incident_frequency": incident_frequency
            })
        
        return {
            "total_oos_incidents": total_incidents,
            "unique_products": unique_products,
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            },
            "products": products
        }
        
    except Exception as e:
        logger.error(f"Error generating OOS products report: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate OOS products report")

@app.post("/reports/oos-products/analyze")
async def analyze_selected_oos_orders(
    request: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Analyze selected OOS orders to generate detailed product breakdown"""
    try:
        from sqlalchemy import func, desc
        
        order_ids = request.get("order_ids", [])
        if not order_ids:
            raise HTTPException(status_code=400, detail="No orders selected")
        
        # Get OOS incidents for selected orders (by order number, not order ID)
        incidents = db.query(OutOfStockIncident).filter(
            OutOfStockIncident.user_id == current_user.id,
            OutOfStockIncident.order_number.in_(order_ids)
        ).all()
        
        if not incidents:
            return {
                "message": "No OOS incidents found for selected orders",
                "total_oos_incidents": 0,
                "unique_products": 0,
                "products": []
            }
        
        # Aggregate by product/variant
        product_data = {}
        for incident in incidents:
            key = f"{incident.product_id}|{incident.variant_id}"
            
            if key not in product_data:
                product_data[key] = {
                    "product_id": incident.product_id,
                    "variant_id": incident.variant_id,
                    "product_title": incident.product_title,
                    "variant_title": incident.variant_title or "",
                    "sku": incident.sku or "",
                    "vendor": incident.vendor or "",
                    "product_type": incident.product_type or "",
                    "total_incidents": 0,
                    "total_quantity_affected": 0,
                    "affected_orders": set(),
                    "locations_affected": set(),
                    "incidents": []
                }
            
            product_data[key]["total_incidents"] += 1
            product_data[key]["total_quantity_affected"] += incident.quantity_attempted
            product_data[key]["affected_orders"].add(incident.order_number)
            if incident.attempted_location_alias:
                product_data[key]["locations_affected"].add(incident.attempted_location_alias)
            
            product_data[key]["incidents"].append({
                "order_number": incident.order_number,
                "incident_date": incident.incident_date.isoformat(),
                "quantity_attempted": incident.quantity_attempted,
                "attempted_location_alias": incident.attempted_location_alias,
                "rule_name": incident.rule_name
            })
        
        # Convert to final format
        products = []
        for data in product_data.values():
            products.append({
                "product_id": data["product_id"],
                "variant_id": data["variant_id"],
                "product_title": data["product_title"],
                "variant_title": data["variant_title"],
                "sku": data["sku"],
                "vendor": data["vendor"],
                "product_type": data["product_type"],
                "total_incidents": data["total_incidents"],
                "total_quantity_affected": data["total_quantity_affected"],
                "affected_orders": len(data["affected_orders"]),
                "affected_order_numbers": list(data["affected_orders"]),
                "locations_affected": list(data["locations_affected"]),
                "incidents": data["incidents"]
            })
        
        # Sort by total incidents descending
        products.sort(key=lambda x: x["total_incidents"], reverse=True)
        
        return {
            "total_oos_incidents": len(incidents),
            "unique_products": len(products),
            "selected_orders": len(order_ids),
            "products": products
        }
        
    except Exception as e:
        logger.error(f"Error analyzing selected OOS orders: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to analyze selected orders")

# Excluded SKU endpoints
@app.get("/settings/excluded-skus", response_model=List[ExcludedSKUResponse])
async def get_excluded_skus(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all excluded SKUs for the current user"""
    try:
        excluded_skus = db.query(ExcludedSKU).filter(
            ExcludedSKU.user_id == current_user.id
        ).order_by(ExcludedSKU.created_at.desc()).all()
        
        return excluded_skus
        
    except Exception as e:
        logger.error(f"Error fetching excluded SKUs: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch excluded SKUs")

@app.post("/settings/excluded-skus", response_model=ExcludedSKUResponse)
async def create_excluded_sku(
    excluded_sku: ExcludedSKUCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new excluded SKU pattern"""
    try:
        # Check if pattern already exists for this user
        existing = db.query(ExcludedSKU).filter(
            ExcludedSKU.user_id == current_user.id,
            ExcludedSKU.sku_pattern == excluded_sku.sku_pattern
        ).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="SKU pattern already exists")
        
        # Create new excluded SKU
        db_excluded_sku = ExcludedSKU(
            user_id=current_user.id,
            sku_pattern=excluded_sku.sku_pattern,
            description=excluded_sku.description
        )
        
        db.add(db_excluded_sku)
        db.commit()
        db.refresh(db_excluded_sku)
        
        logger.info(f"Created excluded SKU pattern '{excluded_sku.sku_pattern}' for user {current_user.id}")
        return db_excluded_sku
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating excluded SKU: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create excluded SKU")

@app.put("/settings/excluded-skus/{sku_id}", response_model=ExcludedSKUResponse)
async def update_excluded_sku(
    sku_id: int,
    excluded_sku_update: ExcludedSKUUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an excluded SKU pattern"""
    try:
        db_excluded_sku = db.query(ExcludedSKU).filter(
            ExcludedSKU.id == sku_id,
            ExcludedSKU.user_id == current_user.id
        ).first()
        
        if not db_excluded_sku:
            raise HTTPException(status_code=404, detail="Excluded SKU not found")
        
        # Check if new pattern conflicts with existing ones
        if excluded_sku_update.sku_pattern and excluded_sku_update.sku_pattern != db_excluded_sku.sku_pattern:
            existing = db.query(ExcludedSKU).filter(
                ExcludedSKU.user_id == current_user.id,
                ExcludedSKU.sku_pattern == excluded_sku_update.sku_pattern,
                ExcludedSKU.id != sku_id
            ).first()
            
            if existing:
                raise HTTPException(status_code=400, detail="SKU pattern already exists")
        
        # Update fields
        if excluded_sku_update.sku_pattern is not None:
            db_excluded_sku.sku_pattern = excluded_sku_update.sku_pattern
        if excluded_sku_update.description is not None:
            db_excluded_sku.description = excluded_sku_update.description
        if excluded_sku_update.is_active is not None:
            db_excluded_sku.is_active = excluded_sku_update.is_active
        
        db.commit()
        db.refresh(db_excluded_sku)
        
        logger.info(f"Updated excluded SKU {sku_id} for user {current_user.id}")
        return db_excluded_sku
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating excluded SKU: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update excluded SKU")

@app.delete("/settings/excluded-skus/{sku_id}")
async def delete_excluded_sku(
    sku_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an excluded SKU pattern"""
    try:
        db_excluded_sku = db.query(ExcludedSKU).filter(
            ExcludedSKU.id == sku_id,
            ExcludedSKU.user_id == current_user.id
        ).first()
        
        if not db_excluded_sku:
            raise HTTPException(status_code=404, detail="Excluded SKU not found")
        
        db.delete(db_excluded_sku)
        db.commit()
        
        logger.info(f"Deleted excluded SKU {sku_id} for user {current_user.id}")
        return {"message": "Excluded SKU deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting excluded SKU: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete excluded SKU")

# ==================== ADMIN ENDPOINTS ====================

@app.post("/admin/auth/login", response_model=AdminTokenResponse)
async def admin_login(
    admin_data: AdminUserLogin,
    request: Request,
    db: Session = Depends(get_db)
):
    admin_user = db.query(AdminUser).filter(
        AdminUser.username == admin_data.username,
        AdminUser.is_active == True
    ).first()
    
    if not admin_user or not verify_admin_password(admin_data.password, admin_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    # Update last login
    admin_user.last_login = datetime.utcnow()
    db.commit()
    
    # Log the login
    log_admin_action(
        db=db,
        admin_user=admin_user,
        action="login",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    
    access_token = create_admin_access_token(data={"sub": admin_user.username})
    return AdminTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=8 * 60 * 60  # 8 hours in seconds
    )

@app.get("/admin/auth/me", response_model=AdminUserResponse)
async def get_current_admin_info(admin_user: AdminUser = Depends(get_current_admin_user)):
    return admin_user

@app.put("/admin/auth/change-password")
async def admin_change_password(
    password_data: AdminUserChangePassword,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    if not verify_admin_password(password_data.current_password, admin_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    admin_user.hashed_password = get_admin_password_hash(password_data.new_password)
    db.commit()
    
    log_admin_action(
        db=db,
        admin_user=admin_user,
        action="password_change",
        target_type="admin_user",
        target_id=str(admin_user.id)
    )
    
    return {"message": "Password changed successfully"}

@app.get("/admin/stats", response_model=SystemStatsResponse)
async def get_system_stats(
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    
    stats = SystemStatsResponse(
        total_users=db.query(User).count(),
        active_users=db.query(User).filter(User.is_active == True).count(),
        total_stores=db.query(ShopifyStore).count(),
        active_stores=db.query(ShopifyStore).filter(ShopifyStore.is_active == True).count(),
        total_rules=db.query(ProcessingRule).count(),
        active_rules=db.query(ProcessingRule).filter(ProcessingRule.is_active == True).count(),
        total_processed_orders=db.query(ProcessedOrder).count(),
        total_order_logs=db.query(OrderLog).count(),
        recent_registrations=db.query(User).filter(User.created_at >= seven_days_ago).count()
    )
    
    return stats

@app.get("/admin/users", response_model=List[UserManagementResponse])
async def get_all_users(
    skip: int = 0,
    limit: int = 100,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    users = db.query(User).offset(skip).limit(limit).all()
    
    user_list = []
    for user in users:
        stores_count = db.query(ShopifyStore).filter(ShopifyStore.user_id == user.id).count()
        rules_count = db.query(ProcessingRule).filter(ProcessingRule.user_id == user.id).count()
        
        # Get last activity from order logs
        last_log = db.query(OrderLog).filter(OrderLog.user_id == user.id).order_by(OrderLog.created_at.desc()).first()
        last_activity = last_log.created_at if last_log else None
        
        user_list.append(UserManagementResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            created_at=user.created_at,
            stores_count=stores_count,
            rules_count=rules_count,
            last_activity=last_activity
        ))
    
    return user_list

@app.put("/admin/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: int,
    admin_user: AdminUser = Depends(require_admin_role(["admin", "super_admin"])),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    old_status = user.is_active
    user.is_active = not user.is_active
    db.commit()
    
    log_admin_action(
        db=db,
        admin_user=admin_user,
        action="user_status_change",
        target_type="user",
        target_id=str(user_id),
        details={"old_status": old_status, "new_status": user.is_active}
    )
    
    return {
        "message": f"User {'activated' if user.is_active else 'deactivated'} successfully",
        "is_active": user.is_active
    }

@app.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: int,
    admin_user: AdminUser = Depends(require_admin_role(["super_admin"])),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_email = user.email
    db.delete(user)
    db.commit()
    
    log_admin_action(
        db=db,
        admin_user=admin_user,
        action="user_delete",
        target_type="user",
        target_id=str(user_id),
        details={"deleted_user_email": user_email}
    )
    
    return {"message": "User deleted successfully"}

@app.get("/admin/stores")
async def get_all_stores(
    skip: int = 0,
    limit: int = 100,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    stores = db.query(ShopifyStore).join(User).offset(skip).limit(limit).all()
    
    store_list = []
    for store in stores:
        store_list.append({
            "id": store.id,
            "shop_domain": store.shop_domain,
            "shop_name": store.shop_name,
            "is_active": store.is_active,
            "created_at": store.created_at,
            "last_sync": store.last_sync,
            "user": {
                "id": store.user.id,
                "email": store.user.email,
                "full_name": store.user.full_name
            }
        })
    
    return store_list

@app.get("/admin/rules")
async def get_all_rules(
    skip: int = 0,
    limit: int = 100,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    rules = db.query(ProcessingRule).join(User).offset(skip).limit(limit).all()
    
    rule_list = []
    for rule in rules:
        rule_list.append({
            "id": rule.id,
            "name": rule.name,
            "description": rule.description,
            "is_active": rule.is_active,
            "priority": rule.priority,
            "created_at": rule.created_at,
            "user": {
                "id": rule.user.id,
                "email": rule.user.email,
                "full_name": rule.user.full_name
            }
        })
    
    return rule_list

@app.get("/admin/audit-logs", response_model=List[AdminAuditLogResponse])
async def get_audit_logs(
    skip: int = 0,
    limit: int = 50,
    action: Optional[str] = None,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    query = db.query(AdminAuditLog).join(AdminUser)
    
    if action:
        query = query.filter(AdminAuditLog.action == action)
    
    logs = query.order_by(AdminAuditLog.created_at.desc()).offset(skip).limit(limit).all()
    return logs

@app.post("/admin/users", response_model=AdminUserResponse)
async def create_admin_user(
    admin_data: AdminUserCreate,
    admin_user: AdminUser = Depends(require_admin_role(["super_admin"])),
    db: Session = Depends(get_db)
):
    # Check if username or email already exists
    existing_user = db.query(AdminUser).filter(
        (AdminUser.username == admin_data.username) | (AdminUser.email == admin_data.email)
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists"
        )
    
    # Create new admin user
    hashed_password = get_admin_password_hash(admin_data.password)
    new_admin = AdminUser(
        username=admin_data.username,
        email=admin_data.email,
        full_name=admin_data.full_name,
        hashed_password=hashed_password,
        role=admin_data.role
    )
    
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    
    log_admin_action(
        db=db,
        admin_user=admin_user,
        action="admin_user_create",
        target_type="admin_user",
        target_id=str(new_admin.id),
        details={"username": admin_data.username, "role": admin_data.role}
    )
    
    return new_admin

@app.get("/admin/order-logs")
async def get_all_order_logs(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    query = db.query(OrderLog).join(User).join(ShopifyStore)
    
    if status_filter:
        query = query.filter(OrderLog.status == status_filter)
    
    logs = query.order_by(OrderLog.created_at.desc()).offset(skip).limit(limit).all()
    
    log_list = []
    for log in logs:
        log_list.append({
            "id": log.id,
            "order_id": log.order_id,
            "order_number": log.order_number,
            "action": log.action,
            "status": log.status,
            "details": log.details,
            "error_message": log.error_message,
            "created_at": log.created_at,
            "user": {
                "id": log.user.id,
                "email": log.user.email,
                "full_name": log.user.full_name
            },
            "store": {
                "id": log.store.id,
                "shop_domain": log.store.shop_domain,
                "shop_name": log.store.shop_name
            }
        })
    
    return log_list

# Database backup/restore endpoints
@app.get("/admin/database/backup")
async def backup_database(
    request: Request,
    admin_user: AdminUser = Depends(require_admin_role(["super_admin"])),
    db: Session = Depends(get_db)
):
    """Download a backup of the database"""
    try:
        # Get the database path from environment or default
        db_url = os.getenv("DATABASE_URL", "sqlite:///app/app.db")
        db_path = db_url.replace("sqlite:///", "")
        # Make path absolute if it's relative
        if not db_path.startswith('/'):
            db_path = os.path.join("/app", db_path)
        
        # Check if database exists
        if not os.path.exists(db_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Database file not found"
            )
        
        # Get database info
        db_info = database_utils.get_database_info(db_path)
        
        # Log the backup action
        log_admin_action(
            db=db,
            admin_user=admin_user,
            action="database_backup",
            details={
                "file_size_mb": db_info["size_mb"],
                "user_count": db_info["user_count"],
                "store_count": db_info["store_count"]
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")
        )
        
        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"shopify_automation_backup_{timestamp}.db"
        
        # Return the file
        return FileResponse(
            path=db_path,
            filename=filename,
            media_type="application/x-sqlite3",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
    except Exception as e:
        logger.error(f"Database backup failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backup failed: {str(e)}"
        )

@app.post("/admin/database/restore")
async def restore_database(
    file: UploadFile = File(...),
    request: Request = None,
    admin_user: AdminUser = Depends(require_admin_role(["super_admin"])),
    db: Session = Depends(get_db)
):
    """Restore database from uploaded file"""
    temp_file_path = None
    try:
        # Check file extension
        if not file.filename.endswith('.db'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file type. Only .db files are allowed"
            )
        
        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as temp_file:
            temp_file_path = temp_file.name
            content = await file.read()
            temp_file.write(content)
        
        # Validate the uploaded file
        is_valid, error_msg = database_utils.validate_sqlite_file(temp_file_path)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
        
        # Get info about uploaded database
        upload_info = database_utils.get_database_info(temp_file_path)
        
        # Target database path
        db_url = os.getenv("DATABASE_URL", "sqlite:///app/app.db")
        target_path = db_url.replace("sqlite:///", "")
        if not target_path.startswith('/'):
            target_path = os.path.join("/app", target_path)
        
        # Get current database info for logging
        current_info = database_utils.get_database_info(target_path)
        
        # Close all database connections
        db.close()
        engine.dispose()
        
        # Perform the restore
        success, error_msg = database_utils.restore_database(
            source_path=temp_file_path,
            target_path=target_path,
            create_pre_restore_backup=True
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_msg
            )
        
        # Re-create database connection
        create_tables()
        new_db = next(get_db())
        
        # Log the restore action in the new database
        try:
            log_admin_action(
                db=new_db,
                admin_user=admin_user,
                action="database_restore",
                details={
                    "uploaded_file": file.filename,
                    "uploaded_size_mb": upload_info["size_mb"],
                    "uploaded_user_count": upload_info["user_count"],
                    "uploaded_store_count": upload_info["store_count"],
                    "previous_size_mb": current_info["size_mb"],
                    "previous_user_count": current_info["user_count"],
                    "previous_store_count": current_info["store_count"]
                },
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent") if request else None
            )
        finally:
            new_db.close()
        
        return {
            "message": "Database restored successfully",
            "details": {
                "users_restored": upload_info["user_count"],
                "stores_restored": upload_info["store_count"],
                "rules_restored": upload_info["rule_count"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database restore failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Restore failed: {str(e)}"
        )
    finally:
        # Clean up temp file
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)

@app.get("/admin/database/info")
async def get_database_info(
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Get information about the current database"""
    try:
        db_url = os.getenv("DATABASE_URL", "sqlite:///app/app.db")
        db_path = db_url.replace("sqlite:///", "")
        if not db_path.startswith('/'):
            db_path = os.path.join("/app", db_path)
        info = database_utils.get_database_info(db_path)
        
        # Get last backup info from audit logs
        last_backup = db.query(AdminAuditLog).filter(
            AdminAuditLog.action == "database_backup"
        ).order_by(AdminAuditLog.created_at.desc()).first()
        
        if last_backup:
            info["last_backup"] = {
                "timestamp": last_backup.created_at.isoformat(),
                "by": last_backup.admin_user.username
            }
        else:
            info["last_backup"] = None
        
        return info
    except Exception as e:
        logger.error(f"Failed to get database info: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get database info: {str(e)}"
        )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)