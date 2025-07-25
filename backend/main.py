from fastapi import FastAPI, Depends, HTTPException, status, Request, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text, case
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date, timezone
import uvicorn
import os
import logging
import asyncio
import json
import tempfile
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from database import engine, get_db, create_tables, SessionLocal
from models import User, ShopifyStore, ProcessingRule, OrderLog, Settings, ProcessedOrder, LocationAlias, LocationMapping, OutOfStockIncident, ExcludedSKU, AdminUser, AdminAuditLog, SystemSettings, FraudAnalysis, FraudDetectionRule, TaskStatus
from auth import get_current_user, create_access_token, verify_password, get_password_hash
from admin_auth import get_current_admin_user, create_admin_access_token, verify_admin_password, get_admin_password_hash, log_admin_action, require_admin_role
from schemas import (
    UserCreate, UserLogin, TokenResponse, ShopifyStoreCreate, RuleCreate, SettingsUpdate, SettingsResponse, OrderLogQuery,
    LocationAliasCreate, LocationAliasUpdate, LocationAliasResponse, LocationMappingCreate, LocationMappingUpdate, 
    LocationMappingResponse, StoreLocationResponse, ExcludedSKUCreate, ExcludedSKUUpdate, ExcludedSKUResponse,
    AdminUserCreate, AdminUserLogin, AdminUserUpdate, AdminUserChangePassword, AdminUserResponse, AdminTokenResponse,
    AdminAuditLogResponse, SystemStatsResponse, UserManagementResponse,
    FraudRuleCreate, FraudRuleResponse, TaskStatusResponse, FailedTasksResponse,
    InventorySearchRequest, InventorySearchResponse, ProductVariantInfo, InventoryLocationLevel, InventoryQuantities,
    InventoryUpdateRequest, InventoryUpdateItem, InventoryUpdateResponse, InventoryUpdateResult, OrderLogResponse
)
from shopify_client import ShopifyClient
from fraud_service import FraudAnalysisService
from tasks import test_celery_connection, process_store_orders, process_all_orders, trigger_fraud_analysis_all_recent, reprocess_fraud_rules_recent
import database_utils
from database_utils import migrate_rules_to_new_format, migrate_fraud_analysis_customer_name, migrate_settings_duplicate_detection_days, migrate_fraud_analysis_shipping_state

security = HTTPBearer()

def _format_timestamp_with_user_timezone(timestamp: datetime, user_id: int, db: Session) -> str:
    """Format timestamp using user's timezone settings"""
    if not timestamp:
        return None
    
    try:
        import pytz
        from datetime import timezone
        
        # Get user's timezone settings
        user_settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        user_timezone = user_settings.timezone if user_settings and user_settings.timezone else "UTC"
        
        # Convert UTC timestamp to user's timezone
        user_tz = pytz.timezone(user_timezone)
        
        # Ensure timestamp is timezone-aware (assume UTC if naive)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        # Convert to user timezone and format
        user_time = timestamp.astimezone(user_tz)
        return user_time.isoformat()
        
    except Exception as e:
        logger.warning(f"Error formatting timestamp with user timezone: {str(e)}")
        # Fallback to UTC isoformat
        return timestamp.isoformat() if timestamp else None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Creating database tables...")
    create_tables()
    print("Database tables created successfully")
    
    # Migrate existing rules to new format
    print("Checking for rule migrations...")
    migrate_rules_to_new_format()
    
    # Migrate fraud analysis table for customer_name field
    print("Checking for fraud analysis table migrations...")
    migrate_fraud_analysis_customer_name()
    
    # Migrate fraud analysis table to rename restricted_state to shipping_state
    print("Checking for fraud analysis shipping_state migration...")
    migrate_fraud_analysis_shipping_state()
    
    # Migrate settings table for duplicate_detection_days field
    print("Checking for settings duplicate_detection_days field migration...")
    migrate_settings_duplicate_detection_days()
    
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

@app.put("/stores/{store_id}/toggle-active")
async def toggle_store_active(
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
    
    old_status = store.is_active
    store.is_active = not store.is_active
    db.commit()
    
    return {
        "id": store.id,
        "shop_domain": store.shop_domain,
        "shop_name": store.shop_name,
        "is_active": store.is_active,
        "created_at": store.created_at,
        "last_sync": store.last_sync,
        "message": f"Store {'activated' if store.is_active else 'deactivated'} successfully"
    }

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

@app.get("/dashboard/enhanced-stats")
async def get_enhanced_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func, and_, or_, case
    
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)
    
    # Processing metrics
    orders_today = db.query(func.count(func.distinct(OrderLog.order_id))).filter(
        OrderLog.user_id == current_user.id,
        OrderLog.created_at >= today_start
    ).scalar() or 0
    
    # Get orders for last 7 days
    orders_by_day = []
    for i in range(7):
        day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = db.query(func.count(func.distinct(OrderLog.order_id))).filter(
            OrderLog.user_id == current_user.id,
            OrderLog.created_at >= day_start,
            OrderLog.created_at < day_end
        ).scalar() or 0
        orders_by_day.append(count)
    orders_by_day.reverse()  # Oldest to newest
    
    # Success rate calculation
    total_orders = db.query(func.count(func.distinct(OrderLog.order_id))).filter(
        OrderLog.user_id == current_user.id,
        OrderLog.created_at >= today_start
    ).scalar() or 0
    
    error_orders = db.query(func.count(func.distinct(OrderLog.order_id))).filter(
        OrderLog.user_id == current_user.id,
        OrderLog.created_at >= today_start,
        OrderLog.status == "error"
    ).scalar() or 0
    
    success_rate = ((total_orders - error_orders) / total_orders * 100) if total_orders > 0 else 100
    
    # Get user settings for sync info
    settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
    is_sync_enabled = settings.auto_sync_enabled if settings else False
    sync_frequency = settings.sync_frequency_minutes if settings else 10
    
    # Get last sync time from stores
    last_sync_time = db.query(func.max(ShopifyStore.last_sync)).filter(
        ShopifyStore.user_id == current_user.id
    ).scalar()
    
    # Calculate next sync time
    next_sync = None
    if last_sync_time and is_sync_enabled:
        next_sync = last_sync_time + timedelta(minutes=sync_frequency)
    
    # Rules triggered today
    rules_triggered = db.query(
        OrderLog.details,
        func.count(func.distinct(OrderLog.order_id)).label('count')
    ).filter(
        OrderLog.user_id == current_user.id,
        OrderLog.created_at >= today_start,
        OrderLog.action == "rule_applied"
    ).group_by(OrderLog.details).all()
    
    rules_triggered_dict = {}
    for detail, count in rules_triggered:
        if detail:
            try:
                import json
                details = json.loads(detail) if isinstance(detail, str) else detail
                rule_name = details.get('rule_name', 'Unknown') if isinstance(details, dict) else 'Unknown'
                rules_triggered_dict[rule_name] = count
            except:
                pass
    
    # Store activity
    store_activity = db.query(
        ShopifyStore.shop_name,
        func.count(func.distinct(OrderLog.order_id)).label('count')
    ).join(
        OrderLog, OrderLog.store_id == ShopifyStore.id
    ).filter(
        ShopifyStore.user_id == current_user.id,
        OrderLog.created_at >= today_start
    ).group_by(ShopifyStore.shop_name).all()
    
    store_activity_dict = {name: count for name, count in store_activity}
    
    # Fraud detection stats (if enabled)
    fraud_analyses_today = 0
    high_risk_count = 0
    active_fraud_rules = 0
    
    try:
        active_fraud_rules = db.query(func.count(FraudDetectionRule.id)).filter(
            FraudDetectionRule.user_id == current_user.id,
            FraudDetectionRule.is_active == True
        ).scalar() or 0
        
        if active_fraud_rules > 0:
            # For now, we'll just count all fraud analyses since the model doesn't have timestamps
            fraud_analyses_today = db.query(func.count(FraudAnalysis.id)).filter(
                FraudAnalysis.user_id == current_user.id
            ).scalar() or 0
            
            high_risk_count = db.query(func.count(FraudAnalysis.id)).filter(
                FraudAnalysis.user_id == current_user.id,
                FraudAnalysis.risk_level == "high"
            ).scalar() or 0
    except Exception as e:
        # Fraud detection models might not exist
        logger.debug(f"Fraud detection query failed: {e}")
        pass
    
    # System health (simplified for now)
    failed_tasks = db.query(func.count(TaskStatus.id)).filter(
        TaskStatus.user_id == current_user.id,
        TaskStatus.status == "failed",
        TaskStatus.created_at >= seven_days_ago
    ).scalar() or 0
    
    # Recent activity
    recent_activity = db.query(OrderLog).filter(
        OrderLog.user_id == current_user.id
    ).order_by(OrderLog.created_at.desc()).limit(10).all()
    
    # Recent errors
    recent_errors = db.query(OrderLog).filter(
        OrderLog.user_id == current_user.id,
        OrderLog.status == "error"
    ).order_by(OrderLog.created_at.desc()).limit(5).all()
    
    # Total processed orders (all time)
    # ProcessedOrder doesn't have user_id, so join with ShopifyStore
    total_processed = db.query(func.count(ProcessedOrder.id)).join(
        ShopifyStore, ProcessedOrder.store_id == ShopifyStore.id
    ).filter(
        ShopifyStore.user_id == current_user.id
    ).scalar() or 0
    
    # Active stores and rules already fetched above
    active_stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id,
        ShopifyStore.is_active == True
    ).count()
    
    total_stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id
    ).count()
    
    active_rules = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id,
        ProcessingRule.is_active == True
    ).count()
    
    total_rules = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id
    ).count()
    
    return {
        "processing": {
            "orders_today": orders_today,
            "orders_last_7_days": orders_by_day,
            "success_rate": round(success_rate, 1),
            "total_processed": total_processed,
            "last_sync": last_sync_time.isoformat() + 'Z' if last_sync_time else None,
            "next_sync": next_sync.isoformat() + 'Z' if next_sync else None,
            "is_syncing": False,  # Would need to check Celery tasks for real status
            "sync_enabled": is_sync_enabled
        },
        "rules": {
            "total": total_rules,
            "active": active_rules,
            "triggered_today": rules_triggered_dict
        },
        "stores": {
            "total": total_stores,
            "active": active_stores,
            "activity": store_activity_dict
        },
        "fraud": {
            "analyses_today": fraud_analyses_today,
            "high_risk_count": high_risk_count,
            "active_rules": active_fraud_rules
        },
        "system": {
            "celery_status": "healthy" if failed_tasks < 5 else "degraded" if failed_tasks < 20 else "down",
            "failed_tasks": failed_tasks
        },
        "recent_activity": [
            {
                "id": log.id,
                "order_id": log.order_id,
                "order_number": log.order_number,
                "store_name": log.store.shop_name if log.store else "Unknown",
                "action": log.action,
                "status": log.status,
                "created_at": log.created_at.isoformat() + 'Z'
            } for log in recent_activity
        ],
        "recent_errors": [
            {
                "id": log.id,
                "order_id": log.order_id,
                "order_number": log.order_number,
                "store_name": log.store.shop_name if log.store else "Unknown",
                "action": log.action,
                "error_message": log.error_message,
                "created_at": log.created_at.isoformat() + 'Z'
            } for log in recent_errors
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
    reset_fraud_analyses = reset_options.get("reset_fraud_analyses", True)
    reset_archived_fraud_analyses = reset_options.get("reset_archived_fraud_analyses", False)
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
        
        # Delete fraud analyses
        if reset_fraud_analyses:
            count = db.query(FraudAnalysis).filter(
                FraudAnalysis.user_id == current_user.id
            ).count()
            db.query(FraudAnalysis).filter(
                FraudAnalysis.user_id == current_user.id
            ).delete()
            deleted_counts["fraud_analyses"] = count
            logger.info(f"Deleted {count} fraud analyses for user {current_user.id}")
        
        # Delete archived fraud analyses
        if reset_archived_fraud_analyses:
            try:
                result = db.execute(
                    text("DELETE FROM fraud_analyses_archive WHERE user_id = :user_id"),
                    {"user_id": current_user.id}
                )
                count = result.rowcount
                deleted_counts["archived_fraud_analyses"] = count
                logger.info(f"Deleted {count} archived fraud analyses for user {current_user.id}")
            except Exception as e:
                logger.warning(f"Could not delete archived fraud analyses: {str(e)}")
                deleted_counts["archived_fraud_analyses"] = 0
        
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
                    "reset_fraud_analyses": reset_fraud_analyses,
                    "reset_archived_fraud_analyses": reset_archived_fraud_analyses,
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
    
    # Count archived fraud analyses using raw SQL since we don't have a model for it
    archived_fraud_count = 0
    try:
        result = db.execute(
            text("SELECT COUNT(*) FROM fraud_analyses_archive WHERE user_id = :user_id"),
            {"user_id": current_user.id}
        ).scalar()
        archived_fraud_count = result or 0
    except Exception as e:
        logger.warning(f"Could not count archived fraud analyses: {str(e)}")
    
    stats = {
        "order_logs": db.query(OrderLog).filter(OrderLog.user_id == current_user.id).count(),
        "processed_orders": db.query(ProcessedOrder).filter(
            ProcessedOrder.store_id.in_(store_ids)
        ).count() if store_ids else 0,
        "oos_incidents": db.query(OutOfStockIncident).filter(
            OutOfStockIncident.user_id == current_user.id
        ).count(),
        "fraud_analyses": db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == current_user.id
        ).count(),
        "archived_fraud_analyses": archived_fraud_count,
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

@app.get("/settings/inventory-verification")
async def get_inventory_verification_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get inventory verification settings"""
    settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
    
    if not settings:
        settings = Settings(user_id=current_user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    return {
        "excluded_tag": settings.inventory_verification_excluded_tag,
        "enabled": os.getenv("ENABLE_INVENTORY_VERIFICATION", "true").lower() == "true"
    }

@app.put("/settings/inventory-verification")
async def update_inventory_verification_settings(
    data: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update inventory verification settings"""
    settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
    
    if not settings:
        settings = Settings(user_id=current_user.id)
        db.add(settings)
    
    # Update excluded tag if provided
    if "excluded_tag" in data:
        settings.inventory_verification_excluded_tag = data.get("excluded_tag")
    
    db.commit()
    db.refresh(settings)
    
    return {
        "excluded_tag": settings.inventory_verification_excluded_tag,
        "enabled": os.getenv("ENABLE_INVENTORY_VERIFICATION", "true").lower() == "true"
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
    search: Optional[str] = None,
    rule_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort_field: Optional[str] = "latest_date",
    sort_direction: Optional[str] = "desc",
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
    if search:
        query = query.filter(OrderLog.order_number.contains(search))
    if rule_id:
        query = query.filter(OrderLog.action == f"applied_rule_{rule_id}")
    
    # Apply date filtering
    if date_from:
        try:
            from_date = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            query = query.filter(OrderLog.created_at >= from_date)
        except ValueError:
            pass  # Ignore invalid date format
    
    if date_to:
        try:
            to_date = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            # Don't modify the to_date since frontend now sends the correct end-of-day time
            query = query.filter(OrderLog.created_at <= to_date)
        except ValueError:
            pass  # Ignore invalid date format
    
    # Parse date filters for reuse
    parsed_date_from = None
    parsed_date_to = None
    
    if date_from:
        try:
            parsed_date_from = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    if date_to:
        try:
            parsed_date_to = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            # Don't modify the parsed_date_to since frontend now sends the correct end-of-day time
        except ValueError:
            pass
    
    # Helper function to apply common filters
    def apply_filters(query):
        if store_id:
            query = query.filter(OrderLog.store_id == store_id)
        if status:
            query = query.filter(OrderLog.status == status)
        if action:
            query = query.filter(OrderLog.action.contains(action))
        if search:
            query = query.filter(OrderLog.order_number.contains(search))
        if rule_id:
            query = query.filter(OrderLog.action == f"applied_rule_{rule_id}")
        if parsed_date_from:
            query = query.filter(OrderLog.created_at >= parsed_date_from)
        if parsed_date_to:
            query = query.filter(OrderLog.created_at <= parsed_date_to)
        return query
    
    # Validate sort parameters
    valid_sort_fields = ['order_number', 'store_name', 'latest_date', 'status', 'action_count']
    if sort_field not in valid_sort_fields:
        sort_field = 'latest_date'
    if sort_direction.lower() not in ['asc', 'desc']:
        sort_direction = 'desc'
    
    # Build different queries based on sort field
    if sort_field == 'store_name':
        # For store name sorting, we need to join with ShopifyStore table
        unique_orders_query = db.query(
            OrderLog.order_number,
            func.max(OrderLog.created_at).label('latest_created_at'),
            func.min(ShopifyStore.shop_name).label('store_name')  # Use min to get any store name for the order
        ).join(ShopifyStore, OrderLog.store_id == ShopifyStore.id).filter(OrderLog.user_id == current_user.id)
        
        unique_orders_query = apply_filters(unique_orders_query)
        unique_orders_query = unique_orders_query.group_by(OrderLog.order_number)
        
    elif sort_field == 'status':
        # For status sorting, we need to calculate order status priority
        unique_orders_query = db.query(
            OrderLog.order_number,
            func.max(OrderLog.created_at).label('latest_created_at'),
            func.max(
                func.case(
                    (OrderLog.status.in_(['error', 'failed']), 0),
                    (OrderLog.status.in_(['match', 'success']), 1),
                    else_=2
                )
            ).label('status_priority')
        ).filter(OrderLog.user_id == current_user.id)
        
        unique_orders_query = apply_filters(unique_orders_query)
        unique_orders_query = unique_orders_query.group_by(OrderLog.order_number)
        
    elif sort_field == 'action_count':
        # For action count sorting, we need to count logs per order
        unique_orders_query = db.query(
            OrderLog.order_number,
            func.max(OrderLog.created_at).label('latest_created_at'),
            func.count(OrderLog.id).label('action_count')
        ).filter(OrderLog.user_id == current_user.id)
        
        unique_orders_query = apply_filters(unique_orders_query)
        unique_orders_query = unique_orders_query.group_by(OrderLog.order_number)
        
    else:
        # For order_number and latest_date (and default), use simple query
        unique_orders_query = db.query(
            OrderLog.order_number,
            func.max(OrderLog.created_at).label('latest_created_at')
        ).filter(OrderLog.user_id == current_user.id)
        
        unique_orders_query = apply_filters(unique_orders_query)
        unique_orders_query = unique_orders_query.group_by(OrderLog.order_number)
    
    # Get total unique orders count
    total_unique_orders = unique_orders_query.count()
    
    # Apply sorting based on sort_field and sort_direction
    if sort_field == 'order_number':
        sort_column = 'order_number'
    elif sort_field == 'store_name':
        sort_column = 'store_name'
    elif sort_field == 'latest_date':
        sort_column = 'latest_created_at'
    elif sort_field == 'status':
        sort_column = 'status_priority'
    elif sort_field == 'action_count':
        sort_column = 'action_count'
    else:
        sort_column = 'latest_created_at'
    
    order_clause = f"{sort_column} {'ASC' if sort_direction.lower() == 'asc' else 'DESC'}"
    
    # Get paginated order numbers with proper sorting
    offset = (page - 1) * per_page
    paginated_orders = unique_orders_query.order_by(text(order_clause)).offset(offset).limit(per_page).all()
    order_numbers = [row[0] for row in paginated_orders]
    
    # Get all logs for these order numbers, maintaining the order of order_numbers
    logs = []
    if order_numbers:
        # Create a CASE statement to preserve the sort order from paginated_orders
        order_case = case(
            *[(OrderLog.order_number == order_num, index) for index, order_num in enumerate(order_numbers)]
        )
        logs = query.filter(OrderLog.order_number.in_(order_numbers)).order_by(order_case, OrderLog.created_at.desc()).all()
    
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
            "total": total_unique_orders,
            "page": page,
            "per_page": per_page,
            "pages": (total_unique_orders + per_page - 1) // per_page,
            "total_logs": len(logs)
        }
    }

@app.get("/order-logs/all-order-ids")
async def get_all_order_ids(
    store_id: Optional[int] = None,
    status: Optional[str] = None,
    action: Optional[str] = None,
    search: Optional[str] = None,
    rule_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all order IDs matching current filters (no pagination)"""
    query = db.query(OrderLog.order_id).filter(OrderLog.user_id == current_user.id)
    
    if store_id:
        query = query.filter(OrderLog.store_id == store_id)
    if status:
        query = query.filter(OrderLog.status == status)
    if action:
        query = query.filter(OrderLog.action.contains(action))
    if search:
        query = query.filter(OrderLog.order_number.contains(search))
    if rule_id:
        query = query.filter(OrderLog.action == f"applied_rule_{rule_id}")
    
    # Apply date filtering (same logic as main endpoint)
    if date_from:
        try:
            from_date = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            query = query.filter(OrderLog.created_at >= from_date)
        except ValueError:
            pass  # Ignore invalid date format
    
    if date_to:
        try:
            to_date = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            query = query.filter(OrderLog.created_at <= to_date)
        except ValueError:
            pass  # Ignore invalid date format
    
    # Get unique order IDs only
    unique_order_ids = query.distinct().all()
    order_ids = [row[0] for row in unique_order_ids]
    
    return {
        "order_ids": order_ids,
        "total_count": len(order_ids)
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
    
    # Warn for very large batches but don't block
    if len(order_ids) > 100:
        logger.warning(f"Large batch retry requested: {len(order_ids)} orders for user {current_user.id}")
    
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

@app.get("/debug/query-costs/{store_id}")
async def debug_query_costs(
    store_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get GraphQL query cost statistics for a store"""
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()
    
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    client = ShopifyClient(store.shop_domain, store.access_token)
    
    return {
        "store": store.shop_name,
        "query_stats": client.get_query_cost_stats()
    }

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
            product_data[key]["total_quantity_affected"] += incident.quantity_attempted or 0
            product_data[key]["affected_orders"].add(incident.order_number)
            if incident.attempted_location_alias:
                product_data[key]["locations_affected"].add(incident.attempted_location_alias)
            
            product_data[key]["incidents"].append({
                "order_number": incident.order_number,
                "incident_date": incident.incident_date.isoformat(),
                "quantity_attempted": incident.quantity_attempted or 0,
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

# Database compaction endpoints
@app.get("/settings/database-stats")
async def get_database_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get database size and fragmentation statistics"""
    import os
    
    try:
        # Get the database file path
        db_url = os.getenv("DATABASE_URL", "sqlite:///./shopify_automation.db")
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            # Handle relative paths
            if not db_path.startswith("/"):
                db_path = os.path.join(os.getcwd(), db_path)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database compaction is only available for SQLite databases"
            )
        
        # Get file size
        if not os.path.exists(db_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Database file not found at {db_path}"
            )
        
        file_size_bytes = os.path.getsize(db_path)
        
        # Get database statistics using SQLite pragmas
        page_count = db.execute(text("PRAGMA page_count")).scalar()
        page_size = db.execute(text("PRAGMA page_size")).scalar()
        freelist_count = db.execute(text("PRAGMA freelist_count")).scalar()
        
        # Calculate statistics
        total_size_bytes = page_count * page_size
        free_size_bytes = freelist_count * page_size
        used_size_bytes = total_size_bytes - free_size_bytes
        fragmentation_percent = (freelist_count / page_count * 100) if page_count > 0 else 0
        
        return {
            "file_size_bytes": file_size_bytes,
            "file_size_mb": round(file_size_bytes / 1024 / 1024, 2),
            "total_pages": page_count,
            "free_pages": freelist_count,
            "page_size": page_size,
            "used_size_bytes": used_size_bytes,
            "used_size_mb": round(used_size_bytes / 1024 / 1024, 2),
            "free_size_bytes": free_size_bytes,
            "free_size_mb": round(free_size_bytes / 1024 / 1024, 2),
            "fragmentation_percent": round(fragmentation_percent, 2),
            "can_compact": freelist_count > 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting database statistics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get database statistics: {str(e)}"
        )

@app.post("/settings/compact-database")
async def compact_database(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Compact the database by running VACUUM to reclaim unused space"""
    import os
    
    try:
        # Get initial statistics
        initial_stats = await get_database_statistics(current_user, db)
        
        # Close the current session to allow VACUUM to run
        db.close()
        
        # Run VACUUM command
        # Note: VACUUM cannot be run inside a transaction
        engine = db.get_bind()
        with engine.connect() as conn:
            # Set isolation level to allow VACUUM
            conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(text("VACUUM"))
            conn.commit()
        
        # Get new statistics after compaction
        # Create a new session for this
        new_db = SessionLocal()
        try:
            final_stats = await get_database_statistics(current_user, new_db)
            
            # Calculate space saved
            space_saved_bytes = initial_stats["file_size_bytes"] - final_stats["file_size_bytes"]
            space_saved_mb = round(space_saved_bytes / 1024 / 1024, 2)
            
            # Log the compaction
            log_entry = OrderLog(
                user_id=current_user.id,
                store_id=0,  # System action
                order_id="SYSTEM_COMPACT",
                order_number="SYSTEM",
                action="database_compacted",
                status="success",
                details={
                    "initial_size_mb": initial_stats["file_size_mb"],
                    "final_size_mb": final_stats["file_size_mb"],
                    "space_saved_mb": space_saved_mb,
                    "initial_fragmentation": initial_stats["fragmentation_percent"],
                    "final_fragmentation": final_stats["fragmentation_percent"]
                }
            )
            new_db.add(log_entry)
            new_db.commit()
            
            return {
                "message": "Database compacted successfully",
                "initial_size_mb": initial_stats["file_size_mb"],
                "final_size_mb": final_stats["file_size_mb"],
                "space_saved_mb": space_saved_mb,
                "space_saved_percent": round((space_saved_bytes / initial_stats["file_size_bytes"] * 100) if initial_stats["file_size_bytes"] > 0 else 0, 2),
                "initial_fragmentation": initial_stats["fragmentation_percent"],
                "final_fragmentation": final_stats["fragmentation_percent"]
            }
        finally:
            new_db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error compacting database: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compact database: {str(e)}"
        )

# ==================== FRAUD DETECTION ENDPOINTS ====================

@app.post("/fraud-detection/analyze/{store_id}")
async def analyze_order_fraud(
    store_id: int,
    order_name: str = Query(..., description="Name of the order to analyze"),
    enhanced: bool = Query(False, description="Use enhanced MCP-based delivery tracking"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Analyze an order for fraud indicators"""
    try:
        # Get the store and verify ownership
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == current_user.id
        ).first()
        
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )
        
        logger.info(f"Fraud analysis request for order {order_name} in store {store_id}")
        
        # Delete any existing analysis for this order to ensure fresh analysis
        deleted_count = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == current_user.id,
            FraudAnalysis.store_id == store_id,
            FraudAnalysis.order_name == order_name
        ).delete(synchronize_session=False)
        
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} existing analysis(es) for order {order_name} to perform fresh analysis")
            db.commit()
        
        # Get order data from Shopify
        logger.info(f"Fetching order data from Shopify for order {order_name}")
        client = ShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        
        order_data = await client.get_order_fraud_data(order_name)
        if not order_data:
            logger.warning(f"Order {order_name} not found in Shopify")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found in Shopify"
            )
        
        logger.info(f"Successfully fetched order data for {order_name}, starting fraud analysis")
        
        # Perform fraud analysis
        fraud_service = FraudAnalysisService(db, store, current_user)
        analysis = fraud_service.analyze_order_fraud(order_data)
        
        logger.info(f"Fraud analysis completed for order {order_name}, analysis ID: {analysis.id if analysis else 'None'}")
        
        if not analysis:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to analyze order for fraud"
            )
        
        return {
            "message": "Fraud analysis completed successfully",
            "analysis_id": analysis.id,
            "status": "completed",
            "order_name": analysis.order_name,
            "analyzed_at": _format_timestamp_with_user_timezone(analysis.analysis_timestamp, current_user.id, db)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing order fraud: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to analyze order for fraud"
        )

@app.get("/fraud-detection/analyses")
async def get_fraud_analyses(
    store_id: Optional[int] = None,
    order_name: Optional[str] = None,
    search: Optional[str] = None,
    risk_level: Optional[str] = None,
    matched_rules: Optional[str] = None,  # Comma-separated list of rules
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    skip: Optional[int] = None,
    limit: Optional[int] = None,
    sort_field: Optional[str] = "analysis_timestamp",
    sort_direction: Optional[str] = "desc",
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get fraud analysis history with pagination and filtering"""
    try:
        # If including archived data, we need to use raw SQL to union both tables
        if include_archived:
            # Build base SQL for both active and archived tables
            base_sql = """
                SELECT *, 'active' as source FROM fraud_analyses WHERE user_id = :user_id
                UNION ALL
                SELECT *, 'archived' as source FROM fraud_analyses_archive WHERE user_id = :user_id
            """
            
            # We'll use a more complex approach for archived data
            # For now, let's warn that it's not fully implemented
            logger.warning("Include archived functionality will be implemented with raw SQL queries")
            
        query = db.query(FraudAnalysis).filter(FraudAnalysis.user_id == current_user.id)
        
        # Apply filters
        if store_id:
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
            query = query.filter(FraudAnalysis.store_id == store_id)
        
        if order_name:
            query = query.filter(FraudAnalysis.order_name.contains(order_name))
        
        # Handle search parameter (searches order name)
        if search:
            query = query.filter(FraudAnalysis.order_name.contains(search))
        
        # Filter by risk level (case-insensitive)
        if risk_level:
            # Convert to uppercase to match database storage format
            query = query.filter(FraudAnalysis.shopify_fraud_risk_level == risk_level.upper())
        
        # Apply date filtering (support both old and new parameter names)
        effective_start_date = date_from or start_date
        if effective_start_date:
            try:
                start_dt = datetime.fromisoformat(effective_start_date.replace('Z', '+00:00'))
                query = query.filter(FraudAnalysis.analysis_timestamp >= start_dt)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid start_date format. Use ISO format."
                )
        
        effective_end_date = date_to or end_date
        if effective_end_date:
            try:
                end_dt = datetime.fromisoformat(effective_end_date.replace('Z', '+00:00'))
                query = query.filter(FraudAnalysis.analysis_timestamp <= end_dt)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid end_date format. Use ISO format."
                )
        
        # Filter by matched rules if provided
        if matched_rules:
            # Parse comma-separated rules
            selected_rules = [rule.strip() for rule in matched_rules.split(',') if rule.strip()]
            
            if selected_rules:
                # Need to filter in Python after fetching all records that match other criteria
                # This is because rule_processing_results is JSON and complex to filter in SQL
                all_analyses = query.all()
                filtered_analyses = []
                
                for analysis in all_analyses:
                    if analysis.rule_processing_results:
                        results = analysis.rule_processing_results
                        if isinstance(results, dict):
                            rule_results = results.get("results", [])
                            
                            # Check for "No rules matched" special case
                            if "No rules matched" in selected_rules:
                                # Check if no rules matched
                                has_matched_rules = any(
                                    r.get("matched", False) for r in rule_results 
                                    if isinstance(r, dict)
                                )
                                if not has_matched_rules and len(selected_rules) == 1:
                                    # Only "No rules matched" is selected
                                    filtered_analyses.append(analysis)
                                # If other rules are also selected with "No rules matched", skip
                                # because an order can't both have no rules and have specific rules
                                continue
                            
                            # Get all matched rules for this analysis
                            matched_rule_names = set()
                            for rule_result in rule_results:
                                if isinstance(rule_result, dict) and rule_result.get("matched", False):
                                    rule_name = rule_result.get("rule_name", "")
                                    if rule_name:
                                        matched_rule_names.add(rule_name)
                            
                            # Check if ALL selected rules are matched (AND operation)
                            if all(rule in matched_rule_names for rule in selected_rules):
                                filtered_analyses.append(analysis)
                    elif "No rules matched" in selected_rules and len(selected_rules) == 1:
                        # No rule results means no rules matched
                        filtered_analyses.append(analysis)
                
                # Convert back to query-like result for pagination
                analysis_ids = [a.id for a in filtered_analyses]
                if analysis_ids:
                    query = db.query(FraudAnalysis).filter(
                        FraudAnalysis.id.in_(analysis_ids),
                        FraudAnalysis.user_id == current_user.id
                    )
                else:
                    # No matches, return empty query
                    query = db.query(FraudAnalysis).filter(FraudAnalysis.id == -1)
        
        # Get total count after all filters
        total = query.count()
        
        # Handle sorting - comprehensive column support
        sort_field_map = {
            # Basic fields
            "order_name": FraudAnalysis.order_name,
            "analysis_timestamp": FraudAnalysis.analysis_timestamp,
            "fraud_score": FraudAnalysis.order_total,  # Using order_total as proxy for score
            "risk_level": FraudAnalysis.shopify_fraud_risk_level,
            "store_name": ShopifyStore.shop_name,
            
            # Customer data
            "customer_name": FraudAnalysis.customer_name,
            "is_first_time_customer": FraudAnalysis.is_first_time_customer,
            "order_total": FraudAnalysis.order_total,
            "current_order_total": FraudAnalysis.current_order_total,
            "previous_order_total": FraudAnalysis.previous_order_total,
            
            # Risk indicators
            "transaction_attempts_count": FraudAnalysis.transaction_attempts_count,
            "duplicate_within_7days": FraudAnalysis.duplicate_within_7days,
            "billing_address_outside_us": FraudAnalysis.billing_address_outside_us,
            "same_billing_shipping": FraudAnalysis.same_billing_shipping,
            "shipping_state": FraudAnalysis.shipping_state,
            
            # Delivery tracking
            "previous_order_delivery_status": FraudAnalysis.previous_order_delivery_status,
            "current_order_delivery_status": FraudAnalysis.current_order_delivery_status,
            
            # Processing metadata  
            "processing_time_seconds": FraudAnalysis.processing_time_seconds,
            "analysis_version": FraudAnalysis.analysis_version,
            "shopify_order_id": FraudAnalysis.shopify_order_id
        }
        
        # Join with ShopifyStore if sorting by store_name
        if sort_field == "store_name":
            query = query.join(ShopifyStore)
        
        # Apply sorting
        sort_column = sort_field_map.get(sort_field, FraudAnalysis.analysis_timestamp)
        if sort_direction == "asc":
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())
        
        # Apply pagination (support both skip/limit and page/per_page)
        if skip is not None and limit is not None:
            offset = skip
            page_size = limit
        else:
            # Fall back to page/per_page with defaults
            actual_page = page or 1
            page_size = per_page or 50
            offset = (actual_page - 1) * page_size
        
        analyses = query.offset(offset).limit(page_size).all()
        
        # Format response
        results = []
        for analysis in analyses:
            # Get store name
            store_name = analysis.store.shop_name if analysis.store else "Unknown Store"
            
            results.append({
                "id": analysis.id,
                "store_id": analysis.store_id,
                "store_name": store_name,
                "order_name": analysis.order_name,
                "shopify_order_id": analysis.shopify_order_id,
                "analysis_timestamp": _format_timestamp_with_user_timezone(analysis.analysis_timestamp, current_user.id, db),
                "is_first_time_customer": analysis.is_first_time_customer,
                "order_total": float(analysis.order_total) if analysis.order_total else None,
                "transaction_attempts_count": analysis.transaction_attempts_count,
                "customer_name": analysis.customer_name,
                "duplicate_within_7days": analysis.duplicate_within_7days,
                "previous_order_delivery_status": analysis.previous_order_delivery_status,
                "previous_order_total": float(analysis.previous_order_total) if analysis.previous_order_total else None,
                "current_order_total": float(analysis.current_order_total) if analysis.current_order_total else None,
                "shopify_fraud_risk_level": analysis.shopify_fraud_risk_level,
                "rule_triggered_ids": analysis.rule_triggered_ids,
                "rule_processing_results": analysis.rule_processing_results,
                "analysis_data": {
                    "first_time_customer": analysis.is_first_time_customer,
                    "duplicate_order_detected": analysis.duplicate_within_7days
                },
                "recommendations": [],  # Can be populated based on analysis
                "fraud_score": 75 if analysis.shopify_fraud_risk_level and analysis.shopify_fraud_risk_level.upper() == "HIGH" else (50 if analysis.shopify_fraud_risk_level and analysis.shopify_fraud_risk_level.upper() == "MEDIUM" else 25),
                "risk_level": (analysis.shopify_fraud_risk_level or "medium").lower()
            })
        
        return {
            "analyses": results,
            "total": total,
            "skip": offset,
            "limit": page_size
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fraud analyses: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get fraud analyses"
        )

@app.get("/fraud-detection/matched-rules")
async def get_all_matched_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all unique matched rules across all fraud analyses for the current user"""
    try:
        # Get all fraud analyses for the user
        analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == current_user.id
        ).all()
        
        # Extract all unique rules from the analyses
        unique_rules = set()
        no_rules_count = 0
        
        for analysis in analyses:
            if analysis.rule_processing_results:
                # Extract matched rules from the JSON results
                results = analysis.rule_processing_results
                if isinstance(results, dict):
                    # Check for the 'results' array structure
                    rule_results = results.get("results", [])
                    has_matched_rules = False
                    
                    for rule_result in rule_results:
                        if isinstance(rule_result, dict) and rule_result.get("matched", False):
                            rule_name = rule_result.get("rule_name", "")
                            if rule_name:
                                unique_rules.add(rule_name)
                                has_matched_rules = True
                    
                    if not has_matched_rules:
                        no_rules_count += 1
                else:
                    no_rules_count += 1
            else:
                no_rules_count += 1
        
        # Convert to sorted list and add "No rules matched" if applicable
        rules_list = sorted(list(unique_rules))
        if no_rules_count > 0:
            rules_list.append("No rules matched")
        
        # Calculate counts for each rule
        rule_counts = {}
        for rule in unique_rules:
            rule_counts[rule] = 0
        
        # Count occurrences of each rule
        for analysis in analyses:
            if analysis.rule_processing_results:
                results = analysis.rule_processing_results
                if isinstance(results, dict):
                    rule_results = results.get("results", [])
                    matched_rules_in_analysis = set()
                    
                    for rule_result in rule_results:
                        if isinstance(rule_result, dict) and rule_result.get("matched", False):
                            rule_name = rule_result.get("rule_name", "")
                            if rule_name:
                                matched_rules_in_analysis.add(rule_name)
                    
                    # Increment count for each matched rule
                    for rule in matched_rules_in_analysis:
                        if rule in rule_counts:
                            rule_counts[rule] += 1
        
        # Add count for "No rules matched" if applicable
        if no_rules_count > 0:
            rule_counts["No rules matched"] = no_rules_count
        
        return {
            "rules": rules_list,
            "rule_counts": rule_counts,
            "total_analyses": len(analyses),
            "analyses_with_no_rules": no_rules_count
        }
        
    except Exception as e:
        logger.error(f"Error getting matched rules: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get matched rules"
        )

@app.get("/fraud-detection/rule-intersection-counts")
async def get_rule_intersection_counts(
    selected_rules: str = Query(None, description="Comma-separated list of currently selected rules"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get counts for each rule showing how many analyses match both the rule and all selected rules"""
    try:
        # Parse selected rules
        selected_rules_list = selected_rules.split(',') if selected_rules else []
        
        # Get all fraud analyses for the user
        analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == current_user.id
        ).all()
        
        # First, find analyses that match ALL selected rules
        matching_analyses_ids = set()
        
        if selected_rules_list:
            for analysis in analyses:
                if analysis.rule_processing_results:
                    results = analysis.rule_processing_results
                    if isinstance(results, dict):
                        rule_results = results.get("results", [])
                        
                        # Get all matched rules for this analysis
                        matched_rules_in_analysis = set()
                        for rule_result in rule_results:
                            if isinstance(rule_result, dict) and rule_result.get("matched", False):
                                rule_name = rule_result.get("rule_name", "")
                                if rule_name:
                                    matched_rules_in_analysis.add(rule_name)
                        
                        # Check if ALL selected rules are in this analysis
                        if all(rule in matched_rules_in_analysis for rule in selected_rules_list):
                            matching_analyses_ids.add(analysis.id)
        else:
            # If no rules selected, all analyses match
            matching_analyses_ids = set(analysis.id for analysis in analyses)
        
        # Now calculate intersection counts for each rule
        all_rules = set()
        rule_intersection_counts = {}
        
        # First pass: collect all unique rules
        for analysis in analyses:
            if analysis.rule_processing_results:
                results = analysis.rule_processing_results
                if isinstance(results, dict):
                    rule_results = results.get("results", [])
                    for rule_result in rule_results:
                        if isinstance(rule_result, dict) and rule_result.get("matched", False):
                            rule_name = rule_result.get("rule_name", "")
                            if rule_name:
                                all_rules.add(rule_name)
        
        # Add "No rules matched" to the set
        all_rules.add("No rules matched")
        
        # Second pass: count intersections
        for rule in all_rules:
            if selected_rules_list and rule in selected_rules_list:
                # For already selected rules, show the count of current filtered results
                rule_intersection_counts[rule] = len(matching_analyses_ids)
            else:
                # For unselected rules, count how many of the matching analyses also have this rule
                count = 0
                for analysis_id in matching_analyses_ids:
                    analysis = next((a for a in analyses if a.id == analysis_id), None)
                    if analysis:
                        if rule == "No rules matched":
                            # Check if this analysis has no matched rules
                            if analysis.rule_processing_results:
                                results = analysis.rule_processing_results
                                if isinstance(results, dict):
                                    rule_results = results.get("results", [])
                                    has_matched_rules = any(
                                        r.get("matched", False) for r in rule_results 
                                        if isinstance(r, dict)
                                    )
                                    if not has_matched_rules:
                                        count += 1
                            else:
                                count += 1
                        else:
                            # Check if this analysis has the specific rule
                            if analysis.rule_processing_results:
                                results = analysis.rule_processing_results
                                if isinstance(results, dict):
                                    rule_results = results.get("results", [])
                                    for rule_result in rule_results:
                                        if (isinstance(rule_result, dict) and 
                                            rule_result.get("matched", False) and
                                            rule_result.get("rule_name", "") == rule):
                                            count += 1
                                            break
                
                rule_intersection_counts[rule] = count
        
        return {
            "rule_counts": rule_intersection_counts,
            "total_matching": len(matching_analyses_ids),
            "selected_rules": selected_rules_list
        }
        
    except Exception as e:
        logger.error(f"Error getting rule intersection counts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get rule intersection counts"
        )

@app.get("/fraud-detection/analysis/{analysis_id}")
async def get_fraud_analysis_details(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed fraud analysis by ID"""
    try:
        analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.id == analysis_id,
            FraudAnalysis.user_id == current_user.id
        ).first()
        
        if not analysis:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud analysis not found"
            )
        
        # Get store name
        store_name = analysis.store.shop_name if analysis.store else "Unknown Store"
        
        return {
            "analysis": {
                "id": analysis.id,
                "user_id": analysis.user_id,
                "store_id": analysis.store_id,
                "order_name": analysis.order_name,
                "shopify_order_id": analysis.shopify_order_id,
                "is_first_time_customer": analysis.is_first_time_customer,
                "order_total": float(analysis.order_total) if analysis.order_total else None,
                "transaction_attempts_count": analysis.transaction_attempts_count,
                "customer_name": analysis.customer_name,
                "duplicate_within_7days": analysis.duplicate_within_7days,
                "previous_order_delivery_status": analysis.previous_order_delivery_status,
                "previous_order_total": float(analysis.previous_order_total) if analysis.previous_order_total else None,
                "current_order_total": float(analysis.current_order_total) if analysis.current_order_total else None,
                "shopify_fraud_risk_level": analysis.shopify_fraud_risk_level,
                "customer_notes": analysis.customer_notes,
                "billing_address_outside_us": analysis.billing_address_outside_us,
                "same_billing_shipping": analysis.same_billing_shipping,
                "shipping_state": analysis.shipping_state,
                "additional_details": analysis.additional_details,
                "current_order_delivery_status": analysis.current_order_delivery_status,
                "raw_shopify_data": analysis.raw_shopify_data,
                "duplicate_match_details": analysis.duplicate_match_details,
                "transaction_details": analysis.transaction_details,
                "risk_assessment_details": analysis.risk_assessment_details,
                "customer_order_history": analysis.customer_order_history,
                "analysis_timestamp": _format_timestamp_with_user_timezone(analysis.analysis_timestamp, current_user.id, db),
                "processing_time_seconds": float(analysis.processing_time_seconds) if analysis.processing_time_seconds else None,
                "analysis_version": analysis.analysis_version
            },
            "store_name": store_name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fraud analysis details: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get fraud analysis details"
        )

@app.get("/fraud-detection/stats")
async def get_fraud_detection_stats(
    store_id: Optional[int] = None,
    days: Optional[int] = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get fraud detection statistics for dashboard"""
    try:
        # Base query
        query = db.query(FraudAnalysis).filter(FraudAnalysis.user_id == current_user.id)
        
        # Filter by store if specified
        if store_id:
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
            query = query.filter(FraudAnalysis.store_id == store_id)
        
        # Filter by date range
        if days:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.filter(FraudAnalysis.analysis_timestamp >= cutoff_date)
        
        # Get all analyses for stats calculation
        analyses = query.all()
        
        total_analyses = len(analyses)
        
        if total_analyses == 0:
            return {
                "total_analyses": 0,
                "period_days": days,
                "stats": {
                    "first_time_customers": {"count": 0, "percentage": 0},
                    "multiple_transaction_attempts": {"count": 0, "percentage": 0},
                    "duplicate_orders": {"count": 0, "percentage": 0},
                    "high_fraud_risk": {"count": 0, "percentage": 0}
                },
                "risk_level_distribution": {
                    "low": {"count": 0, "percentage": 0},
                    "medium": {"count": 0, "percentage": 0},
                    "high": {"count": 0, "percentage": 0},
                    "unknown": {"count": 0, "percentage": 0}
                },
                "average_order_total": 0,
                "recent_analyses": []
            }
        
        # Calculate statistics
        first_time_customers = sum(1 for a in analyses if a.is_first_time_customer)
        multiple_attempts = sum(1 for a in analyses if a.transaction_attempts_count and a.transaction_attempts_count > 1)
        duplicate_orders = sum(1 for a in analyses if a.duplicate_within_7days)
        high_fraud_risk = sum(1 for a in analyses if a.shopify_fraud_risk_level and a.shopify_fraud_risk_level.upper() == 'HIGH')
        
        # Risk level distribution
        risk_levels = {"low": 0, "medium": 0, "high": 0, "unknown": 0}
        for analysis in analyses:
            level = (analysis.shopify_fraud_risk_level or "unknown").lower()
            risk_levels[level] = risk_levels.get(level, 0) + 1
        
        # Average order total
        order_totals = [float(a.order_total) for a in analyses if a.order_total]
        average_order_total = sum(order_totals) / len(order_totals) if order_totals else 0
        
        # Recent analyses (last 5)
        recent_analyses = sorted(analyses, key=lambda x: x.analysis_timestamp or datetime.min, reverse=True)[:5]
        recent_list = []
        for analysis in recent_analyses:
            store_name = analysis.store.shop_name if analysis.store else "Unknown Store"
            recent_list.append({
                "id": analysis.id,
                "order_name": analysis.order_name,
                "store_name": store_name,
                "analyzed_at": _format_timestamp_with_user_timezone(analysis.analysis_timestamp, current_user.id, db),
                "fraud_risk_level": analysis.shopify_fraud_risk_level or "unknown"
            })
        
        return {
            "total_analyses": total_analyses,
            "period_days": days,
            "stats": {
                "first_time_customers": {
                    "count": first_time_customers,
                    "percentage": round((first_time_customers / total_analyses) * 100, 1)
                },
                "multiple_transaction_attempts": {
                    "count": multiple_attempts,
                    "percentage": round((multiple_attempts / total_analyses) * 100, 1)
                },
                "duplicate_orders": {
                    "count": duplicate_orders,
                    "percentage": round((duplicate_orders / total_analyses) * 100, 1)
                },
                "high_fraud_risk": {
                    "count": high_fraud_risk,
                    "percentage": round((high_fraud_risk / total_analyses) * 100, 1)
                }
            },
            "risk_level_distribution": {
                level: {
                    "count": count,
                    "percentage": round((count / total_analyses) * 100, 1)
                }
                for level, count in risk_levels.items()
            },
            "average_order_total": round(average_order_total, 2),
            "recent_analyses": recent_list
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fraud detection stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get fraud detection statistics"
        )

@app.get("/fraud-detection/archived-analyses")
async def get_archived_fraud_analyses(
    store_id: Optional[int] = None,
    order_name: Optional[str] = None,
    search: Optional[str] = None,
    archive_reason: Optional[str] = None,  # order_fulfilled or order_cancelled
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    sort_field: Optional[str] = "archived_at",
    sort_direction: Optional[str] = "desc",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get archived fraud analyses with filtering and pagination"""
    try:
        # Build query for archived analyses
        params = {
            "user_id": current_user.id,
            "skip": skip,
            "limit": limit
        }
        
        # Start building the WHERE clause
        where_clauses = ["user_id = :user_id"]
        
        # Apply filters
        if store_id:
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
            where_clauses.append("store_id = :store_id")
            params["store_id"] = store_id
        
        if order_name:
            where_clauses.append("order_name LIKE :order_name")
            params["order_name"] = f"%{order_name}%"
        
        if search:
            where_clauses.append("order_name LIKE :search")
            params["search"] = f"%{search}%"
        
        if archive_reason:
            where_clauses.append("archive_reason = :archive_reason")
            params["archive_reason"] = archive_reason
        
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                where_clauses.append("archived_at >= :start_date")
                params["start_date"] = start_dt
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid start_date format. Use ISO format."
                )
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                where_clauses.append("archived_at <= :end_date")
                params["end_date"] = end_dt
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid end_date format. Use ISO format."
                )
        
        # Build the WHERE clause
        where_sql = " AND ".join(where_clauses)
        
        # Map sort fields
        sort_field_map = {
            "order_name": "order_name",
            "risk_level": "shopify_fraud_risk_level",
            "customer_name": "customer_name",
            "order_total": "order_total",
            "archived_at": "archived_at",
            "archive_reason": "archive_reason"
        }
        
        # Validate and set sort field
        actual_sort_field = sort_field_map.get(sort_field, "archived_at")
        sort_dir = "DESC" if sort_direction.upper() == "DESC" else "ASC"
        
        # Count total archived analyses matching filters
        count_sql = f"SELECT COUNT(*) as total FROM fraud_analyses_archive WHERE {where_sql}"
        count_result = db.execute(text(count_sql), params).fetchone()
        total_count = count_result.total if count_result else 0
        
        # Get archived analyses with pagination
        query_sql = f"""
            SELECT * FROM fraud_analyses_archive 
            WHERE {where_sql}
            ORDER BY {actual_sort_field} {sort_dir}
            LIMIT :limit OFFSET :skip
        """
        
        result = db.execute(text(query_sql), params)
        
        # Convert results to list of dicts
        analyses = []
        for row in result:
            analysis_dict = dict(row._mapping)
            
            # Parse JSON fields
            json_fields = [
                'raw_shopify_data', 'duplicate_match_details', 'transaction_details',
                'risk_assessment_details', 'customer_order_history', 'delivery_analytics',
                'rule_triggered_ids', 'rule_processing_results'
            ]
            
            for field in json_fields:
                if analysis_dict.get(field) and isinstance(analysis_dict[field], str):
                    try:
                        analysis_dict[field] = json.loads(analysis_dict[field])
                    except Exception as e:
                        logger.warning(f"Failed to parse JSON field {field}: {e}")
                        pass
            
            # Get store name
            store = db.query(ShopifyStore).filter(
                ShopifyStore.id == analysis_dict['store_id']
            ).first()
            
            analyses.append({
                **analysis_dict,
                "store_name": store.shop_name if store else "Unknown Store",
                "is_archived": True
            })
        
        return {
            "total": total_count,
            "skip": skip,
            "limit": limit,
            "data": analyses
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting archived fraud analyses: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get archived fraud analyses"
        )

@app.post("/fraud-detection/archive/{analysis_id}")
async def manually_archive_fraud_analysis(
    analysis_id: int,
    archive_reason: str = "manual_archive",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually archive a specific fraud analysis for testing purposes"""
    try:
        # Find the analysis
        analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.id == analysis_id,
            FraudAnalysis.user_id == current_user.id
        ).first()
        
        if not analysis:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud analysis not found"
            )
        
        # Validate archive reason
        valid_reasons = ["manual_archive", "order_fulfilled", "order_cancelled"]
        if archive_reason not in valid_reasons:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid archive reason. Must be one of: {', '.join(valid_reasons)}"
            )
        
        # Use the fraud archive service to archive the analysis
        from fraud_archive_service import FraudArchiveService
        archive_service = FraudArchiveService(db)
        
        # Archive the analysis
        archive_service._archive_analysis(analysis, archive_reason)
        
        # Commit the transaction
        db.commit()
        
        return {
            "message": "Fraud analysis archived successfully",
            "analysis_id": analysis_id,
            "order_name": analysis.order_name,
            "archive_reason": archive_reason,
            "archived_at": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error manually archiving fraud analysis: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to archive fraud analysis"
        )

@app.post("/fraud-detection/archive-fulfilled-cancelled")
async def bulk_archive_fulfilled_cancelled_orders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger the archive process for all fulfilled and cancelled orders"""
    logger.info(f"Bulk archive requested by user {current_user.id} ({current_user.email})")
    try:
        from fraud_archive_service import FraudArchiveService
        
        archive_service = FraudArchiveService(db)
        
        # Use the existing archive service method that fetches fresh data from Shopify
        result = await archive_service.archive_fulfilled_and_cancelled_analyses(current_user.id)
        
        # Create a more informative message based on the results
        archived_count = result["archived"]
        checked_count = result["checked"]
        
        # Get remaining count
        remaining_count = result.get("total_remaining", 0)
        
        # Get user's batch size setting
        settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
        batch_size = settings.reconciliation_batch_size if settings else 500
        
        if archived_count == 0:
            if checked_count == 0:
                message = "No fraud analyses found to reconcile."
            else:
                message = f"Checked {checked_count} orders - all are still unfulfilled. Nothing to reconcile at this time."
        else:
            message = f"Reconciliation completed. Archived {archived_count} out of {checked_count} orders."
        
        # Add note about remaining analyses
        if remaining_count > 0:
            message += f" ({remaining_count} more orders to check - run again to continue, batch size: {batch_size})"
        
        # Use the actual archived orders from the service
        archived_orders = result.get("archived_orders", [])
        
        return {
            "message": message,
            "archived_count": archived_count,
            "checked_count": checked_count,
            "archived_orders": archived_orders,
            "total_remaining": remaining_count
        }
        
    except Exception as e:
        logger.error(f"Error during bulk archive process: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run bulk archive process: {str(e)}"
        )

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

# Fraud Rule Management endpoints
def _normalize_fraud_rule_conditions(conditions):
    """Normalize fraud rule conditions - capitalize fraud risk level values"""
    if isinstance(conditions, dict):
        if 'conditions' in conditions:
            # Handle new format with operator and conditions array
            normalized_conditions = []
            for condition in conditions['conditions']:
                if (condition.get('field') == 'fraud_risk_level' and 
                    condition.get('operator') in ['risk_level_equals', 'risk_level_not_equals']):
                    # Capitalize the risk level value to match Shopify's format
                    condition = condition.copy()
                    condition['value'] = str(condition['value']).upper()
                normalized_conditions.append(condition)
            
            return {
                'operator': conditions['operator'],
                'conditions': normalized_conditions
            }
        else:
            # Handle legacy format - direct conditions array
            normalized_conditions = []
            for condition in conditions:
                if (condition.get('field') == 'fraud_risk_level' and 
                    condition.get('operator') in ['risk_level_equals', 'risk_level_not_equals']):
                    # Capitalize the risk level value to match Shopify's format
                    condition = condition.copy()
                    condition['value'] = str(condition['value']).upper()
                normalized_conditions.append(condition)
            return normalized_conditions
    return conditions

@app.post("/fraud-rules", status_code=status.HTTP_201_CREATED, response_model=FraudRuleResponse)
async def create_fraud_rule(
    rule_data: FraudRuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new fraud detection rule"""
    try:
        # Normalize conditions through the schema validator and convert to dict
        # rule_data.conditions is already normalized to dict format by the validator
        if hasattr(rule_data.conditions, 'dict'):
            conditions_to_save = rule_data.conditions.dict()
        else:
            conditions_to_save = rule_data.conditions
        
        # Normalize fraud risk level values to uppercase
        conditions_to_save = _normalize_fraud_rule_conditions(conditions_to_save)
        
        db_rule = FraudDetectionRule(
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
        
        logger.info(f"Created fraud detection rule '{rule_data.name}' for user {current_user.id}")
        
        return FraudRuleResponse(
            id=db_rule.id,
            name=db_rule.name,
            description=db_rule.description,
            conditions=db_rule.conditions,
            actions=db_rule.actions,
            priority=db_rule.priority,
            delay_ms=db_rule.delay_ms,
            is_active=db_rule.is_active,
            created_at=db_rule.created_at,
            updated_at=db_rule.updated_at
        )
        
    except Exception as e:
        logger.error(f"Error creating fraud rule: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create fraud rule: {str(e)}"
        )

@app.get("/fraud-rules", response_model=List[FraudRuleResponse])
async def get_fraud_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all fraud detection rules for the current user"""
    try:
        rules = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.user_id == current_user.id
        ).order_by(FraudDetectionRule.priority.asc()).all()
        
        return [
            FraudRuleResponse(
                id=rule.id,
                name=rule.name,
                description=rule.description,
                conditions=rule.conditions,
                actions=rule.actions,
                priority=rule.priority,
                delay_ms=rule.delay_ms,
                is_active=rule.is_active,
                created_at=rule.created_at,
                updated_at=rule.updated_at
            )
            for rule in rules
        ]
        
    except Exception as e:
        logger.error(f"Error fetching fraud rules: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch fraud rules: {str(e)}"
        )

@app.get("/fraud-rules/schema")
async def get_fraud_rule_schema(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get available fields, operators, and actions for fraud rule creation"""
    try:
        from rule_engine import RuleEngine
        engine = RuleEngine()
        
        # Get user's duplicate detection days setting
        user_settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
        duplicate_detection_days = user_settings.duplicate_detection_days if user_settings else 7
        
        # Get fraud-specific fields for rule conditions
        fraud_fields = [
            {"field": "first_time_customer", "label": "First Time Customer", "type": "boolean"},
            {"field": "order_total", "label": "Order Total", "type": "number"},
            {"field": "fraud_order_total_multiple", "label": "Order Total Multiple (vs Previous Order)", "type": "number"},
            {"field": "transaction_attempts", "label": "Transaction Attempts", "type": "number"},
            {"field": "customer_name", "label": "Customer Name", "type": "string"},
            {"field": "duplicate_within_7days", "label": f"Duplicate Within {duplicate_detection_days} Days", "type": "boolean"},
            {"field": "previous_order_delivery_status", "label": "Previous Order Delivery Status", "type": "string"},
            {"field": "previous_order_total", "label": "Previous Order Total", "type": "number"},
            {"field": "current_order_total", "label": "Current Order Total", "type": "number"},
            {"field": "fraud_risk_level", "label": "Shopify Fraud Risk Level", "type": "string"},
            {"field": "customer_notes", "label": "Customer Notes", "type": "string"},
            {"field": "billing_outside_us", "label": "Billing Address Outside US", "type": "boolean"},
            {"field": "same_billing_shipping", "label": "Same Billing & Shipping", "type": "boolean"},
            {"field": "shipping_state", "label": "Shipping State", "type": "string"},
            {"field": "days_since_last_delivery", "label": "Days Since Last Delivery", "type": "number"},
            {"field": "previous_order_cancelled", "label": "Previous Order Cancelled", "type": "boolean"},
            {"field": "customer_total_orders", "label": "Customer Total Orders", "type": "number"}
        ]
        
        # Get fraud-specific operators
        fraud_operators = [
            {"operator": "equals", "label": "Equals", "types": ["string", "number", "boolean"]},
            {"operator": "not_equals", "label": "Not Equals", "types": ["string", "number", "boolean"]},
            {"operator": "greater_than", "label": "Greater Than", "types": ["number"]},
            {"operator": "less_than", "label": "Less Than", "types": ["number"]},
            {"operator": "greater_than_or_equal", "label": "Greater Than or Equal", "types": ["number"]},
            {"operator": "less_than_or_equal", "label": "Less Than or Equal", "types": ["number"]},
            {"operator": "multiple_greater_than", "label": "Multiple Greater Than", "types": ["number"]},
            {"operator": "contains", "label": "Contains", "types": ["string"]},
            {"operator": "not_contains", "label": "Does Not Contain", "types": ["string"]},
            {"operator": "starts_with", "label": "Starts With", "types": ["string"]},
            {"operator": "ends_with", "label": "Ends With", "types": ["string"]},
            {"operator": "in_list", "label": "In List", "types": ["string"]},
            {"operator": "not_in_list", "label": "Not In List", "types": ["string"]},
            {"operator": "is_empty", "label": "Is Empty", "types": ["string"]},
            {"operator": "is_not_empty", "label": "Is Not Empty", "types": ["string"]},
            {"operator": "risk_level_equals", "label": "Risk Level Equals", "types": ["string"]},
            {"operator": "delivery_status_contains", "label": "Delivery Status Contains", "types": ["string"]},
            {"operator": "fraud_ratio_greater_than", "label": "Ratio Greater Than", "types": ["number"]},
            {"operator": "fraud_ratio_less_than", "label": "Ratio Less Than", "types": ["number"]}
        ]
        
        # Get fraud-specific action types
        fraud_actions = [
            {"type": "do_nothing", "label": "Do Nothing", "parameters": []},
            {"type": "add_tag", "label": "Add Tag", "parameters": ["tags"]},
            {"type": "remove_tag", "label": "Remove Tag", "parameters": ["tags"]},
            {"type": "place_on_hold", "label": "Place Order on Hold", "parameters": []}
        ]
        
        return {
            "fields": fraud_fields,
            "operators": fraud_operators,
            "action_types": fraud_actions
        }
        
    except Exception as e:
        logger.error(f"Error getting fraud rule schema: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fraud rule schema: {str(e)}"
        )

@app.get("/fraud-rules/{rule_id}", response_model=FraudRuleResponse)
async def get_fraud_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific fraud detection rule"""
    try:
        rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.id == rule_id,
            FraudDetectionRule.user_id == current_user.id
        ).first()
        
        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud rule not found"
            )
        
        return FraudRuleResponse(
            id=rule.id,
            name=rule.name,
            description=rule.description,
            conditions=rule.conditions,
            actions=rule.actions,
            priority=rule.priority,
            delay_ms=rule.delay_ms,
            is_active=rule.is_active,
            created_at=rule.created_at,
            updated_at=rule.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching fraud rule {rule_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch fraud rule: {str(e)}"
        )

@app.put("/fraud-rules/{rule_id}", response_model=FraudRuleResponse)
async def update_fraud_rule(
    rule_id: int,
    rule_data: FraudRuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing fraud detection rule"""
    try:
        rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.id == rule_id,
            FraudDetectionRule.user_id == current_user.id
        ).first()
        
        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud rule not found"
            )
        
        # Normalize conditions through the schema validator and convert to dict
        if hasattr(rule_data.conditions, 'dict'):
            conditions_to_save = rule_data.conditions.dict()
        else:
            conditions_to_save = rule_data.conditions
        
        # Normalize fraud risk level values to uppercase
        conditions_to_save = _normalize_fraud_rule_conditions(conditions_to_save)
        
        # Update rule fields
        rule.name = rule_data.name
        rule.description = rule_data.description
        rule.conditions = conditions_to_save
        rule.actions = [action.dict() for action in rule_data.actions]
        rule.priority = rule_data.priority
        rule.delay_ms = rule_data.delay_ms
        rule.is_active = rule_data.is_active
        rule.updated_at = func.now()
        
        db.commit()
        db.refresh(rule)
        
        logger.info(f"Updated fraud detection rule '{rule_data.name}' for user {current_user.id}")
        
        return FraudRuleResponse(
            id=rule.id,
            name=rule.name,
            description=rule.description,
            conditions=rule.conditions,
            actions=rule.actions,
            priority=rule.priority,
            delay_ms=rule.delay_ms,
            is_active=rule.is_active,
            created_at=rule.created_at,
            updated_at=rule.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating fraud rule {rule_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update fraud rule: {str(e)}"
        )

@app.delete("/fraud-rules/{rule_id}")
async def delete_fraud_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a fraud detection rule"""
    try:
        rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.id == rule_id,
            FraudDetectionRule.user_id == current_user.id
        ).first()
        
        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud rule not found"
            )
        
        db.delete(rule)
        db.commit()
        
        logger.info(f"Deleted fraud detection rule '{rule.name}' for user {current_user.id}")
        return {"message": "Fraud rule deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting fraud rule {rule_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete fraud rule: {str(e)}"
        )

@app.put("/fraud-rules/{rule_id}/toggle")
async def toggle_fraud_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Toggle the active status of a fraud detection rule"""
    try:
        rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.id == rule_id,
            FraudDetectionRule.user_id == current_user.id
        ).first()
        
        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud rule not found"
            )
        
        # Toggle the active status
        rule.is_active = not rule.is_active
        rule.updated_at = func.now()
        db.commit()
        
        status_text = "activated" if rule.is_active else "deactivated"
        logger.info(f"Fraud detection rule '{rule.name}' {status_text} for user {current_user.id}")
        
        return {
            "message": f"Fraud rule {status_text} successfully",
            "is_active": rule.is_active
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling fraud rule {rule_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to toggle fraud rule: {str(e)}"
        )


# Fraud Sync Control Endpoints
@app.get("/settings/fraud-sync-status")
async def get_fraud_sync_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current fraud sync status and statistics"""
    try:
        # Get recent fraud analyses count (last 7 days)
        from datetime import datetime, timedelta, timezone
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        recent_analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == current_user.id,
            FraudAnalysis.analysis_timestamp >= week_ago
        ).count()
        
        # Get total fraud analyses
        total_analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == current_user.id
        ).count()
        
        # Get active fraud rules count
        active_fraud_rules = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.user_id == current_user.id,
            FraudDetectionRule.is_active == True
        ).count()
        
        # Get active stores count
        active_stores = db.query(ShopifyStore).filter(
            ShopifyStore.user_id == current_user.id,
            ShopifyStore.is_active == True
        ).count()
        
        # Check for running fraud tasks
        from models import TaskStatus
        from datetime import datetime, timedelta, timezone
        
        # Clean up stale running tasks (older than 2 minutes)
        stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
        stale_tasks = db.query(TaskStatus).filter(
            TaskStatus.task_name.in_(["trigger_fraud_analysis", "reprocess_fraud_rules"]),
            TaskStatus.status == "running",
            TaskStatus.created_at < stale_cutoff
        ).all()
        
        for task in stale_tasks:
            logger.warning(f"Cleaning up stale task {task.task_id} (created {task.created_at})")
            task.status = "failed"
            task.error_message = "Task timed out"
            task.completed_at = datetime.utcnow()
        
        if stale_tasks:
            db.commit()
        
        # Get currently running tasks
        running_fraud_tasks = db.query(TaskStatus).filter(
            TaskStatus.task_name.in_(["trigger_fraud_analysis", "reprocess_fraud_rules"]),
            TaskStatus.status == "running"
        ).all()
        
        return {
            "recent_analyses_count": recent_analyses,
            "total_analyses_count": total_analyses,
            "active_fraud_rules_count": active_fraud_rules,
            "active_stores_count": active_stores,
            "is_processing": len(running_fraud_tasks) > 0,
            "running_tasks": [
                {
                    "task_id": task.task_id,
                    "task_type": task.task_name,
                    "started_at": task.started_at.replace(tzinfo=timezone.utc).isoformat() if task.started_at else None,
                    "status": task.status
                }
                for task in running_fraud_tasks
            ]
        }
        
    except Exception as e:
        logger.error(f"Error getting fraud sync status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fraud sync status: {str(e)}"
        )


@app.post("/settings/trigger-fraud-analysis")
async def trigger_fraud_analysis(
    days_back: int = Query(default=7, ge=1, le=30, description="Days back to analyze orders"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger fraud analysis for all recent orders"""
    try:
        # Check if there are any active stores
        active_stores = db.query(ShopifyStore).filter(
            ShopifyStore.user_id == current_user.id,
            ShopifyStore.is_active == True
        ).count()
        
        if active_stores == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active stores found. Please connect and activate at least one store."
            )
        
        # Check if there's already a running fraud analysis task
        from models import TaskStatus
        running_task = db.query(TaskStatus).filter(
            TaskStatus.task_name == "trigger_fraud_analysis",
            TaskStatus.status == "running"
        ).first()
        
        if running_task:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Fraud analysis is already running. Please wait for it to complete."
            )
        
        # Start the fraud analysis task
        task = trigger_fraud_analysis_all_recent.delay(current_user.id, days_back)
        
        # Create task status record
        from models import TaskStatus
        task_status = TaskStatus(
            task_id=task.id,
            task_name="trigger_fraud_analysis",
            status="running",
            started_at=datetime.now(timezone.utc)
        )
        db.add(task_status)
        db.commit()
        
        logger.info(f"Fraud analysis task started for user {current_user.id} (task ID: {task.id})")
        
        return {
            "message": f"Fraud analysis started for orders from the last {days_back} days",
            "task_id": task.id,
            "days_back": days_back,
            "stores_count": active_stores
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering fraud analysis: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger fraud analysis: {str(e)}"
        )


@app.get("/debug/task-status")
async def debug_task_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug endpoint to check task status"""
    from models import TaskStatus
    from datetime import datetime, timedelta, timezone
    
    # Get all fraud-related tasks
    all_tasks = db.query(TaskStatus).filter(
        TaskStatus.task_name.in_(["trigger_fraud_analysis", "reprocess_fraud_rules"])
    ).order_by(TaskStatus.created_at.desc()).limit(10).all()
    
    # Clean up stale running tasks (older than 5 minutes)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    stale_tasks = db.query(TaskStatus).filter(
        TaskStatus.task_name.in_(["trigger_fraud_analysis", "reprocess_fraud_rules"]),
        TaskStatus.status == "running",
        TaskStatus.created_at < stale_cutoff
    ).all()
    
    for task in stale_tasks:
        logger.warning(f"Cleaning up stale task {task.task_id} - marking as failed")
        task.status = "failed"
        task.error_message = "Task timed out - marked as failed after 5 minutes"
        task.completed_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "recent_tasks": [
            {
                "task_id": task.task_id,
                "task_name": task.task_name,
                "status": task.status,
                "created_at": task.created_at,
                "completed_at": task.completed_at,
                "result": task.result,
                "error_message": task.error_message
            }
            for task in all_tasks
        ],
        "cleaned_stale_tasks": len(stale_tasks)
    }


@app.post("/settings/reprocess-fraud-rules")
async def reprocess_fraud_rules(
    days_back: int = Query(default=7, ge=1, le=30, description="Days back to reprocess fraud rules"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reprocess fraud rules for recent fraud analyses"""
    try:
        # Check if there are any active fraud rules
        active_fraud_rules = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.user_id == current_user.id,
            FraudDetectionRule.is_active == True
        ).count()
        
        if active_fraud_rules == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active fraud detection rules found. Please create and activate at least one fraud rule."
            )
        
        # Check for recent fraud analyses
        from datetime import datetime, timedelta, timezone
        import pytz
        
        # Get user's timezone settings
        user_settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
        user_timezone = user_settings.timezone if user_settings and user_settings.timezone else "UTC"
        
        # Calculate date range using user's timezone
        user_tz = pytz.timezone(user_timezone)
        now_user_tz = datetime.now(user_tz)
        since_date_user_tz = now_user_tz - timedelta(days=days_back)
        since_date = since_date_user_tz.astimezone(timezone.utc)
        
        recent_analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.user_id == current_user.id,
            FraudAnalysis.analysis_timestamp >= since_date
        ).count()
        
        if recent_analyses == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No fraud analyses found from the last {days_back} days. Please run fraud analysis first."
            )
        
        # Check if there's already a running fraud rules task
        from models import TaskStatus
        running_task = db.query(TaskStatus).filter(
            TaskStatus.task_name == "reprocess_fraud_rules",
            TaskStatus.status == "running"
        ).first()
        
        if running_task:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Fraud rule reprocessing is already running. Please wait for it to complete."
            )
        
        # Start the fraud rules reprocessing task
        task = reprocess_fraud_rules_recent.delay(current_user.id, days_back)
        
        # Create task status record
        from models import TaskStatus
        task_status = TaskStatus(
            task_id=task.id,
            task_name="reprocess_fraud_rules",
            status="running",
            started_at=datetime.now(timezone.utc)
        )
        db.add(task_status)
        db.commit()
        
        logger.info(f"Fraud rules reprocessing task started for user {current_user.id} (task ID: {task.id})")
        
        return {
            "message": f"Fraud rule reprocessing started for analyses from the last {days_back} days",
            "task_id": task.id,
            "days_back": days_back,
            "analyses_count": recent_analyses,
            "rules_count": active_fraud_rules
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reprocessing fraud rules: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reprocess fraud rules: {str(e)}"
        )


# Order Hold Management Endpoints
@app.get("/orders/{order_id}/fulfillment-orders")
async def get_order_fulfillment_orders(
    order_id: str,
    store_id: int = Query(..., description="Store ID to get the order from"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all fulfillment orders for a given order"""
    logger.info(f"Fulfillment orders endpoint called with order_id: '{order_id}', store_id: {store_id}")
    try:
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
        
        # URL decode the order_id in case it's encoded
        import urllib.parse
        decoded_order_id = urllib.parse.unquote(order_id)
        logger.info(f"Looking up order: original='{order_id}', decoded='{decoded_order_id}'")
        
        # Get fulfillment orders
        client = ShopifyClient(store.shop_domain, store.access_token)
        fulfillment_orders = await client.get_fulfillment_orders_for_order(decoded_order_id)
        
        # If no fulfillment orders found, try to get order info for debugging
        if not fulfillment_orders:
            logger.warning(f"No fulfillment orders found for order {decoded_order_id}")
            try:
                # Try to get basic order info to see if the order exists
                order_info = await client.get_order_by_id(decoded_order_id)
                if order_info:
                    order_status = order_info.get('displayFulfillmentStatus', 'unknown')
                    financial_status = order_info.get('displayFinancialStatus', 'unknown')
                    logger.info(f"Order {decoded_order_id} exists but has no fulfillment orders. Status: {order_status}, Financial: {financial_status}")
                    
                    # Provide specific guidance based on order status
                    if order_status == "UNFULFILLED":
                        debug_info = "Order is unfulfilled but has no fulfillment orders yet. This may be a new order - fulfillment orders are typically created automatically by Shopify within a few minutes. Try again shortly."
                    elif order_status == "FULFILLED":
                        debug_info = "Order is already fulfilled - no fulfillment orders available for holds"
                    elif order_status == "CANCELLED":
                        debug_info = "Order is cancelled - no fulfillment orders available"
                    else:
                        debug_info = f"Order exists but has no fulfillment orders (Status: {order_status})"
                    
                    return {
                        "order_id": decoded_order_id,
                        "fulfillment_orders": [],
                        "order_exists": True,
                        "order_status": order_status,
                        "financial_status": financial_status,
                        "debug_info": debug_info
                    }
                else:
                    logger.warning(f"Order {decoded_order_id} not found in Shopify")
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Order {decoded_order_id} not found in Shopify"
                    )
            except Exception as debug_error:
                logger.error(f"Error getting order info for debugging: {str(debug_error)}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order {decoded_order_id} not found or inaccessible"
                )
        
        return {
            "order_id": decoded_order_id,
            "fulfillment_orders": fulfillment_orders
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fulfillment orders for order {order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fulfillment orders: {str(e)}"
        )


@app.get("/fulfillment-orders")
async def get_order_fulfillment_orders_alt(
    order_id: str = Query(..., description="Order ID to get fulfillment orders for"),
    store_id: int = Query(..., description="Store ID to get the order from"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all fulfillment orders for a given order (alternative endpoint with query params)"""
    logger.info(f"Alternative fulfillment orders endpoint called with order_id: '{order_id}', store_id: {store_id}")
    try:
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
        
        # URL decode the order_id in case it's encoded
        import urllib.parse
        decoded_order_id = urllib.parse.unquote(order_id)
        logger.info(f"Looking up order: original='{order_id}', decoded='{decoded_order_id}'")
        
        # Get fulfillment orders
        client = ShopifyClient(store.shop_domain, store.access_token)
        fulfillment_orders = await client.get_fulfillment_orders_for_order(decoded_order_id)
        
        # If no fulfillment orders found, try to get order info for debugging
        if not fulfillment_orders:
            logger.warning(f"No fulfillment orders found for order {decoded_order_id}")
            try:
                # Try to get basic order info to see if the order exists
                order_info = await client.get_order_by_id(decoded_order_id)
                if order_info:
                    order_status = order_info.get('displayFulfillmentStatus', 'unknown')
                    financial_status = order_info.get('displayFinancialStatus', 'unknown')
                    logger.info(f"Order {decoded_order_id} exists but has no fulfillment orders. Status: {order_status}, Financial: {financial_status}")
                    
                    # Provide specific guidance based on order status
                    if order_status == "UNFULFILLED":
                        debug_info = "Order is unfulfilled but has no fulfillment orders yet. This may be a new order - fulfillment orders are typically created automatically by Shopify within a few minutes. Try again shortly."
                    elif order_status == "FULFILLED":
                        debug_info = "Order is already fulfilled - no fulfillment orders available for holds"
                    elif order_status == "CANCELLED":
                        debug_info = "Order is cancelled - no fulfillment orders available"
                    else:
                        debug_info = f"Order exists but has no fulfillment orders (Status: {order_status})"
                    
                    return {
                        "order_id": decoded_order_id,
                        "fulfillment_orders": [],
                        "order_exists": True,
                        "order_status": order_status,
                        "financial_status": financial_status,
                        "debug_info": debug_info
                    }
                else:
                    logger.warning(f"Order {decoded_order_id} not found in Shopify")
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Order {decoded_order_id} not found in Shopify"
                    )
            except Exception as debug_error:
                logger.error(f"Error getting order info for debugging: {str(debug_error)}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order {decoded_order_id} not found or inaccessible"
                )
        
        return {
            "order_id": decoded_order_id,
            "fulfillment_orders": fulfillment_orders
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fulfillment orders for order {order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fulfillment orders: {str(e)}"
        )


@app.get("/debug/fulfillment-orders-raw")
async def debug_fulfillment_orders_raw(
    order_id: str = Query(..., description="Order ID to debug"),
    store_id: int = Query(..., description="Store ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug endpoint to see raw GraphQL response for fulfillment orders"""
    import traceback
    import urllib.parse
    
    logger.info(f"Debug fulfillment orders raw - User: {current_user.email}, Store: {store_id}, Order: {order_id}")
    
    try:
        # Verify store ownership
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == current_user.id
        ).first()
        
        if not store:
            logger.error(f"Store not found - Store ID: {store_id}, User ID: {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )
        
        logger.info(f"Store found - Domain: {store.shop_domain}, Store Name: {store.shop_name}")
        
        # URL decode the order_id
        decoded_order_id = urllib.parse.unquote(order_id)
        logger.info(f"Decoded order ID: {decoded_order_id}")
        
        # Get raw GraphQL response
        try:
            client = ShopifyClient(store.shop_domain, store.access_token)
            logger.info(f"ShopifyClient initialized for domain: {store.shop_domain}")
        except Exception as client_error:
            logger.error(f"Failed to initialize ShopifyClient: {str(client_error)}")
            logger.error(f"Client error traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "Failed to initialize Shopify client",
                    "details": str(client_error),
                    "traceback": traceback.format_exc()
                }
            )
        
        # Make the same query as get_fulfillment_orders_for_order but return raw response
        query = """
        query getFulfillmentOrders($orderId: ID!) {
            order(id: $orderId) {
                id
                name
                displayFulfillmentStatus
                displayFinancialStatus
                createdAt
                updatedAt
                fulfillmentOrders(first: 20) {
                    edges {
                        node {
                            id
                            status
                            requestStatus
                            createdAt
                            updatedAt
                            assignedLocation {
                                location {
                                    id
                                    name
                                }
                            }
                            lineItems(first: 20) {
                                edges {
                                    node {
                                        id
                                        totalQuantity
                                        remainingQuantity
                                        variant {
                                            id
                                            title
                                            sku
                                        }
                                    }
                                }
                            }
                            fulfillmentHolds {
                                id
                                reason
                                reasonNotes
                                displayReason
                                handle
                                heldByApp {
                                    id
                                    title
                                }
                                heldByRequestingApp
                            }
                        }
                    }
                }
            }
        }
        """
        
        variables = {"orderId": decoded_order_id}
        logger.info(f"Making GraphQL request with variables: {variables}")
        
        try:
            raw_result = await client._make_graphql_request(query, variables)
            logger.info(f"GraphQL request successful - Response keys: {list(raw_result.keys()) if isinstance(raw_result, dict) else 'Not a dict'}")
            
            # Check if there are any errors in the GraphQL response
            if isinstance(raw_result, dict) and "errors" in raw_result:
                logger.error(f"GraphQL errors in response: {raw_result['errors']}")
            
            return {
                "success": True,
                "order_id": decoded_order_id,
                "store_id": store_id,
                "store_domain": store.shop_domain,
                "store_name": store.shop_name,
                "raw_graphql_response": raw_result
            }
            
        except Exception as graphql_error:
            logger.error(f"GraphQL request failed: {str(graphql_error)}")
            logger.error(f"GraphQL error traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "GraphQL request failed",
                    "details": str(graphql_error),
                    "traceback": traceback.format_exc(),
                    "order_id": decoded_order_id,
                    "store_domain": store.shop_domain,
                    "query": query,
                    "variables": variables
                }
            )
        
    except HTTPException:
        # Re-raise HTTPExceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error in debug endpoint: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Unexpected error occurred",
                "details": str(e),
                "traceback": traceback.format_exc(),
                "order_id": order_id,
                "store_id": store_id,
                "user_id": current_user.id
            }
        )


@app.post("/fulfillment-orders/{fulfillment_order_id}/hold")
async def apply_order_hold(
    fulfillment_order_id: str,
    store_id: int = Query(..., description="Store ID"),
    reason: str = Query(..., description="Hold reason (e.g., HIGH_RISK_OF_FRAUD, AWAITING_PAYMENT, etc.)"),
    reason_notes: str = Query("", description="Additional notes about the hold"),
    notify_merchant: bool = Query(True, description="Whether to notify the merchant"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Apply a hold to a fulfillment order"""
    try:
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
        
        # Validate reason
        valid_reasons = [
            "AWAITING_PAYMENT",
            "HIGH_RISK_OF_FRAUD",
            "INCORRECT_ADDRESS",
            "INVENTORY_OUT_OF_STOCK",
            "AWAITING_RETURN_ITEMS",
            "UNKNOWN_DELIVERY_DATE",
            "OTHER"
        ]
        
        if reason not in valid_reasons:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid hold reason. Must be one of: {', '.join(valid_reasons)}"
            )
        
        # Apply the hold
        client = ShopifyClient(store.shop_domain, store.access_token)
        result = await client.apply_fulfillment_hold(
            fulfillment_order_id,
            reason,
            reason_notes,
            notify_merchant
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to apply hold: {result.get('errors', 'Unknown error')}"
            )
        
        # Log the action
        from models import OrderLog
        log_entry = OrderLog(
            user_id=current_user.id,
            store_id=store.id,
            order_id=result["fulfillment_order"]["id"] if result["fulfillment_order"] else None,
            order_number=f"Fulfillment Order {fulfillment_order_id}",
            action="fulfillment_hold_applied",
            status="info",
            details={
                "fulfillment_order_id": fulfillment_order_id,
                "hold_reason": reason,
                "hold_notes": reason_notes,
                "notify_merchant": notify_merchant,
                "hold_id": result["hold"]["id"] if result["hold"] else None,
                "rule_name": "Manual Hold"
            }
        )
        db.add(log_entry)
        db.commit()
        
        return {
            "success": True,
            "message": f"Hold applied successfully to fulfillment order {fulfillment_order_id}",
            "fulfillment_order": result["fulfillment_order"],
            "hold": result["hold"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying hold to fulfillment order {fulfillment_order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply hold: {str(e)}"
        )


@app.post("/fulfillment-orders/{fulfillment_order_id}/release-hold")
async def release_order_hold(
    fulfillment_order_id: str,
    store_id: int = Query(..., description="Store ID"),
    hold_ids: List[str] = Query(None, description="Specific hold IDs to release (releases all if not provided)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Release a hold from a fulfillment order"""
    try:
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
        
        # Release the hold
        client = ShopifyClient(store.shop_domain, store.access_token)
        result = await client.release_fulfillment_hold(fulfillment_order_id, hold_ids)
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to release hold: {result.get('errors', 'Unknown error')}"
            )
        
        # Log the action
        from models import OrderLog
        log_entry = OrderLog(
            user_id=current_user.id,
            store_id=store.id,
            order_id=result["fulfillment_order"]["id"] if result["fulfillment_order"] else None,
            order_number=f"Fulfillment Order {fulfillment_order_id}",
            action="fulfillment_hold_released",
            status="info",
            details={
                "fulfillment_order_id": fulfillment_order_id,
                "hold_ids": hold_ids,
                "rule_name": "Manual Hold Release"
            }
        )
        db.add(log_entry)
        db.commit()
        
        return {
            "success": True,
            "message": f"Hold released successfully from fulfillment order {fulfillment_order_id}",
            "fulfillment_order": result["fulfillment_order"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error releasing hold from fulfillment order {fulfillment_order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to release hold: {str(e)}"
        )


@app.post("/fulfillment-order-hold")
async def apply_order_hold_query(
    fulfillment_order_id: str = Query(..., description="Fulfillment Order ID (Shopify GID)"),
    store_id: int = Query(..., description="Store ID"),
    reason: str = Query(..., description="Hold reason (e.g., HIGH_RISK_OF_FRAUD, AWAITING_PAYMENT, etc.)"),
    reason_notes: str = Query("", description="Additional notes about the hold"),
    notify_merchant: bool = Query(True, description="Whether to notify the merchant"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Apply a hold to a fulfillment order using query parameters to avoid URL encoding issues with Shopify GIDs"""
    try:
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
        
        # Validate reason
        valid_reasons = [
            "AWAITING_PAYMENT",
            "HIGH_RISK_OF_FRAUD",
            "INCORRECT_ADDRESS",
            "INVENTORY_OUT_OF_STOCK",
            "AWAITING_RETURN_ITEMS",
            "UNKNOWN_DELIVERY_DATE",
            "OTHER"
        ]
        
        if reason not in valid_reasons:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid hold reason. Must be one of: {', '.join(valid_reasons)}"
            )
        
        # Apply the hold
        client = ShopifyClient(store.shop_domain, store.access_token)
        result = await client.apply_fulfillment_hold(
            fulfillment_order_id,
            reason,
            reason_notes,
            notify_merchant
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to apply hold: {result.get('errors', 'Unknown error')}"
            )
        
        # Log the action
        from models import OrderLog
        log_entry = OrderLog(
            user_id=current_user.id,
            store_id=store.id,
            order_id=result["fulfillment_order"]["id"] if result["fulfillment_order"] else None,
            order_number=f"Fulfillment Order {fulfillment_order_id}",
            action="fulfillment_hold_applied",
            status="info",
            details={
                "fulfillment_order_id": fulfillment_order_id,
                "hold_reason": reason,
                "hold_notes": reason_notes,
                "notify_merchant": notify_merchant,
                "hold_id": result["hold"]["id"] if result["hold"] else None,
                "rule_name": "Manual Hold"
            }
        )
        db.add(log_entry)
        db.commit()
        
        return {
            "success": True,
            "message": f"Hold applied successfully to fulfillment order {fulfillment_order_id}",
            "fulfillment_order": result["fulfillment_order"],
            "hold": result["hold"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying hold to fulfillment order {fulfillment_order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply hold: {str(e)}"
        )


@app.get("/debug/fraud-order/{analysis_id}")
async def debug_fraud_order(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug endpoint to understand fraud analysis order data"""
    try:
        # Get fraud analysis
        analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.id == analysis_id,
            FraudAnalysis.user_id == current_user.id
        ).first()
        
        if not analysis:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud analysis not found"
            )
        
        # Get store
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == analysis.store_id,
            ShopifyStore.user_id == current_user.id
        ).first()
        
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )
        
        # Try to get order by different methods
        client = ShopifyClient(store.shop_domain, store.access_token)
        
        debug_info = {
            "analysis_id": analysis_id,
            "stored_order_id": analysis.shopify_order_id,
            "order_name": analysis.order_name,
            "store_id": analysis.store_id,
            "store_name": store.shop_name,
            "methods_tried": []
        }
        
        # Method 1: Try with stored ID as-is
        try:
            order_1 = await client.get_order_by_id(analysis.shopify_order_id)
            debug_info["methods_tried"].append({
                "method": "stored_id_as_is",
                "id_used": analysis.shopify_order_id,
                "success": bool(order_1),
                "order_status": order_1.get('displayFulfillmentStatus') if order_1 else None
            })
        except Exception as e:
            debug_info["methods_tried"].append({
                "method": "stored_id_as_is",
                "id_used": analysis.shopify_order_id,
                "success": False,
                "error": str(e)
            })
        
        # Method 2: Try with GID format
        gid_format = f"gid://shopify/Order/{analysis.shopify_order_id}" if not analysis.shopify_order_id.startswith('gid://') else analysis.shopify_order_id
        try:
            order_2 = await client.get_order_by_id(gid_format)
            debug_info["methods_tried"].append({
                "method": "gid_format",
                "id_used": gid_format,
                "success": bool(order_2),
                "order_status": order_2.get('displayFulfillmentStatus') if order_2 else None
            })
        except Exception as e:
            debug_info["methods_tried"].append({
                "method": "gid_format",
                "id_used": gid_format,
                "success": False,
                "error": str(e)
            })
        
        # Method 3: Try to find by name
        try:
            order_3 = await client.get_order_fraud_data(analysis.order_name)
            debug_info["methods_tried"].append({
                "method": "by_name",
                "name_used": analysis.order_name,
                "success": bool(order_3),
                "found_id": order_3.get('order_info', {}).get('id') if order_3 else None
            })
        except Exception as e:
            debug_info["methods_tried"].append({
                "method": "by_name",
                "name_used": analysis.order_name,
                "success": False,
                "error": str(e)
            })
        
        return debug_info
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error debugging fraud order {analysis_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to debug fraud order: {str(e)}"
        )


# Task Status endpoints
@app.get("/task-status/failed", response_model=FailedTasksResponse)
async def get_failed_tasks(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get failed tasks for the current user with pagination"""
    query = db.query(TaskStatus).filter(
        TaskStatus.user_id == current_user.id,
        TaskStatus.status == "failed"
    )
    
    # Apply search filter
    if search:
        query = query.filter(
            (TaskStatus.task_name.contains(search)) |
            (TaskStatus.error_message.contains(search))
        )
    
    # Apply date filters
    if date_from:
        try:
            from_date = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            query = query.filter(TaskStatus.created_at >= from_date)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            query = query.filter(TaskStatus.created_at <= to_date)
        except ValueError:
            pass
    
    # Get total count
    total = query.count()
    
    # Calculate pagination
    pages = (total + per_page - 1) // per_page
    offset = (page - 1) * per_page
    
    # Get tasks with pagination
    tasks = query.order_by(TaskStatus.created_at.desc()).offset(offset).limit(per_page).all()
    
    # Convert to response format with timezone handling
    task_responses = []
    for task in tasks:
        task_responses.append(TaskStatusResponse(
            id=task.id,
            user_id=task.user_id,
            task_id=task.task_id,
            task_name=task.task_name,
            status=task.status,
            result=task.result,
            error_message=task.error_message,
            started_at=_format_timestamp_with_user_timezone(task.started_at, current_user.id, db) if task.started_at else None,
            completed_at=_format_timestamp_with_user_timezone(task.completed_at, current_user.id, db) if task.completed_at else None,
            created_at=_format_timestamp_with_user_timezone(task.created_at, current_user.id, db)
        ))
    
    return FailedTasksResponse(
        tasks=task_responses,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages
    )

@app.get("/task-status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get details for a specific task"""
    task = db.query(TaskStatus).filter(
        TaskStatus.id == task_id,
        TaskStatus.user_id == current_user.id
    ).first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    return TaskStatusResponse(
        id=task.id,
        user_id=task.user_id,
        task_id=task.task_id,
        task_name=task.task_name,
        status=task.status,
        result=task.result,
        error_message=task.error_message,
        started_at=_format_timestamp_with_user_timezone(task.started_at, current_user.id, db) if task.started_at else None,
        completed_at=_format_timestamp_with_user_timezone(task.completed_at, current_user.id, db) if task.completed_at else None,
        created_at=_format_timestamp_with_user_timezone(task.created_at, current_user.id, db)
    )


@app.delete("/task-status/{task_id}")
async def clear_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Clear a specific task"""
    task = db.query(TaskStatus).filter(
        TaskStatus.id == task_id,
        TaskStatus.user_id == current_user.id
    ).first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    db.delete(task)
    db.commit()
    
    return {"message": "Task cleared successfully"}


# Inventory Management Endpoints
@app.get("/inventory/location-aliases")
async def get_inventory_location_aliases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all active location aliases for the current user"""
    try:
        aliases = db.query(LocationAlias).filter(
            LocationAlias.user_id == current_user.id,
            LocationAlias.is_active == True
        ).order_by(LocationAlias.alias_name).all()
        
        return [
            {
                "id": alias.id,
                "alias_name": alias.alias_name,
                "mapping_count": len([m for m in alias.mappings if m.is_active])
            }
            for alias in aliases
        ]
        
    except Exception as e:
        logger.error(f"Error getting location aliases: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get location aliases: {str(e)}"
        )


@app.get("/inventory/search")
async def search_inventory_by_barcode(
    barcode: str = Query(..., description="UPC barcode to search for"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search for products by barcode across all active stores"""
    try:
        from schemas import InventorySearchResponse, ProductVariantInfo, InventoryLocationLevel, InventoryQuantities
        
        # Get all active stores
        stores = db.query(ShopifyStore).filter(
            ShopifyStore.user_id == current_user.id,
            ShopifyStore.is_active == True
        ).all()
        
        if not stores:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active stores found"
            )
        
        all_variants = []
        variant_store_map = {}  # Map variant_id to store info
        
        # Search for products by barcode in each store
        for store in stores:
            client = ShopifyClient(store.shop_domain, store.access_token)
            try:
                variants = await client.get_product_by_barcode(barcode)
                for variant in variants:
                    variant_id = variant.get("id")
                    if variant_id and variant_id not in variant_store_map:
                        all_variants.append(ProductVariantInfo(
                            variant_id=variant_id,
                            title=variant.get("title", ""),
                            sku=variant.get("sku"),
                            barcode=variant.get("barcode"),
                            product_id=variant.get("product", {}).get("id", ""),
                            product_title=variant.get("product", {}).get("title", ""),
                            inventory_item_id=variant.get("inventoryItem", {}).get("id", "")
                        ))
                        variant_store_map[variant_id] = []
                    
                    if variant_id:
                        variant_store_map[variant_id].append(store)
                        
            except Exception as e:
                logger.error(f"Error searching barcode in store {store.shop_name}: {str(e)}")
                continue
        
        if not all_variants:
            return InventorySearchResponse(
                barcode=barcode,
                variants=[],
                inventory_levels=[]
            )
        
        return InventorySearchResponse(
            barcode=barcode,
            variants=all_variants,
            inventory_levels=[]  # Will be populated by the next endpoint
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching inventory by barcode: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search inventory: {str(e)}"
        )


@app.get("/inventory/{barcode}/levels")
async def get_inventory_levels(
    barcode: str,
    location_aliases: Optional[str] = Query(None, description="Comma-separated list of location aliases to filter by"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get inventory levels for a barcode across all stores and locations"""
    try:
        from schemas import InventorySearchResponse, ProductVariantInfo, InventoryLocationLevel, InventoryQuantities
        
        # First search for the product
        stores = db.query(ShopifyStore).filter(
            ShopifyStore.user_id == current_user.id,
            ShopifyStore.is_active == True
        ).all()
        
        if not stores:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active stores found"
            )
        
        # Track unique inventory locations to avoid duplicates
        inventory_levels_map = {}
        # Track product info (we'll consolidate variants with same barcode)
        consolidated_product = None
        variant_ids_seen = set()
        # Track inventory item IDs per store
        inventory_item_ids_by_store = {}
        
        # Parse location alias filter
        filter_aliases = []
        if location_aliases:
            filter_aliases = [alias.strip() for alias in location_aliases.split(",") if alias.strip()]
        
        # Get location aliases for this user
        location_aliases_db = db.query(LocationAlias).filter(
            LocationAlias.user_id == current_user.id,
            LocationAlias.is_active == True
        ).all()
        
        alias_map = {}
        # If filtering by aliases, also create a set of allowed store:location pairs
        allowed_locations = set()
        
        for alias in location_aliases_db:
            for mapping in alias.mappings:
                if mapping.is_active:
                    key = f"{mapping.store_id}:{mapping.shopify_location_id}"
                    alias_map[key] = alias.alias_name
                    
                    # If we're filtering and this alias is in the filter list, add to allowed set
                    if filter_aliases and alias.alias_name in filter_aliases:
                        allowed_locations.add(key)
        
        # Create async tasks for all stores - PARALLEL EXECUTION
        async def process_store(store):
            client = ShopifyClient(store.shop_domain, store.access_token)
            results = {
                "store": store,
                "variants": [],
                "inventory_levels": {},
                "error": None
            }
            
            try:
                # Get variants for this barcode
                variants = await client.get_product_by_barcode(barcode)
                results["variants"] = variants
                
                # Get location mappings for this store
                location_mappings = db.query(LocationMapping).filter(
                    LocationMapping.store_id == store.id,
                    LocationMapping.is_active == True
                ).all()
                
                if location_mappings and variants:
                    # Process first variant (they should all have same inventory)
                    variant = variants[0] if variants else None
                    if variant and variant.get("id"):
                        # Check if we have optimized inventory data from the product query
                        if "_inventory_levels" in variant:
                            # Use the pre-fetched inventory data
                            location_ids = [m.shopify_location_id for m in location_mappings]
                            filtered_inventory = {}
                            for loc_id in location_ids:
                                if loc_id in variant["_inventory_levels"]:
                                    filtered_inventory[loc_id] = variant["_inventory_levels"][loc_id]
                            
                            results["inventory_levels"] = {
                                "variant_id": variant["id"],
                                "inventory_item_id": variant.get("inventoryItem", {}).get("id"),
                                "inventory_levels": filtered_inventory
                            }
                        else:
                            # Fallback to separate query if needed
                            location_ids = [m.shopify_location_id for m in location_mappings]
                            inventory_data = await client.get_inventory_across_locations(variant["id"], location_ids)
                            results["inventory_levels"] = inventory_data
                        
            except Exception as e:
                logger.error(f"Error getting inventory for store {store.shop_name}: {str(e)}")
                results["error"] = str(e)
            
            return results
        
        # Execute all store queries in parallel
        store_tasks = [process_store(store) for store in stores]
        store_results = await asyncio.gather(*store_tasks, return_exceptions=True)
        
        # Process results
        for result in store_results:
            if isinstance(result, Exception):
                logger.error(f"Store processing failed: {str(result)}")
                continue
                
            if result.get("error"):
                continue
                
            store = result["store"]
            variants = result["variants"]
            
            for variant in variants:
                variant_id = variant.get("id")
                if not variant_id:
                    continue
                
                # Skip if we've already processed this variant ID
                if variant_id in variant_ids_seen:
                    continue
                variant_ids_seen.add(variant_id)
                
                # Store the inventory item ID for this store
                inventory_item_id = variant.get("inventoryItem", {}).get("id", "")
                if inventory_item_id:
                    inventory_item_ids_by_store[store.id] = inventory_item_id
                
                # Use the first variant's info as the consolidated product info
                if not consolidated_product:
                    consolidated_product = ProductVariantInfo(
                        variant_id=variant_id,
                        title=variant.get("title", ""),
                        sku=variant.get("sku"),
                        barcode=barcode,  # Use the searched barcode
                        product_id=variant.get("product", {}).get("id", ""),
                        product_title=variant.get("product", {}).get("title", ""),
                        inventory_item_id=inventory_item_id  # This will be store-specific
                    )
                
                # Process inventory levels
                inventory_data = result.get("inventory_levels", {})
                for location_id, level_data in inventory_data.get("inventory_levels", {}).items():
                    quantities = level_data.get("quantities", {})
                    alias_key = f"{store.id}:{location_id}"
                    
                    # Use store_id + location_id as unique key
                    inv_key = f"{store.id}:{location_id}"
                    
                    # Skip if we're filtering and this location is not in the allowed set
                    if filter_aliases and inv_key not in allowed_locations:
                        continue
                    
                    # Only add if we haven't seen this location yet
                    if inv_key not in inventory_levels_map:
                        inventory_level = InventoryLocationLevel(
                            store_id=store.id,
                            store_name=store.shop_name,
                            location_id=location_id,
                            location_name=level_data.get("location_name", ""),
                            location_alias=alias_map.get(alias_key),
                            quantities=InventoryQuantities(
                                available=quantities.get("available", 0),
                                on_hand=quantities.get("on_hand", 0),
                                committed=quantities.get("committed", 0)
                            )
                        )
                        # Add the store-specific inventory item ID as a custom field
                        inventory_level.inventory_item_id = inventory_item_ids_by_store.get(store.id)
                        inventory_levels_map[inv_key] = inventory_level
        
        # Convert map to list
        inventory_levels = list(inventory_levels_map.values())
        
        # Check if inventory verification is enabled
        verification_enabled = os.getenv("ENABLE_INVENTORY_VERIFICATION", "true").lower() == "true"
        verification_summary = None
        
        if verification_enabled and consolidated_product:
            # Get user's verification settings
            settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
            excluded_tag = settings.inventory_verification_excluded_tag if settings else None
            
            # Run verification per location for accurate counts - PARALLEL EXECUTION
            
            # Create a map of store clients
            store_clients = {}
            for store in stores:
                store_clients[store.id] = ShopifyClient(store.shop_domain, store.access_token)
            
            # Create verification tasks for parallel execution
            async def verify_location(level):
                client = store_clients.get(level.store_id)
                if not client:
                    return None
                    
                try:
                    result = await client.get_unfulfilled_orders_for_verification(
                        barcode=barcode,
                        days_back=4,
                        excluded_tag=excluded_tag,
                        location_id=level.location_id
                    )
                    
                    location_quantity = result.get("total_quantity", 0)
                    
                    # Add verification data to the level
                    level.quantities.verification_quantity = location_quantity
                    level.quantities.verification_metadata = {
                        "orders_processed": result.get("orders_processed", 0),
                        "days_back": result.get("days_back", 4),
                        "excluded_tag": result.get("excluded_tag"),
                        "location_id": result.get("location_id"),
                        "error": result.get("error")
                    }
                    
                    return {
                        "store_id": level.store_id,
                        "location_id": level.location_id,
                        "quantity": location_quantity,
                        "orders_processed": result.get("orders_processed", 0),
                        "error": result.get("error")
                    }
                    
                except Exception as e:
                    logger.error(f"Verification error for store {level.store_id} location {level.location_id}: {str(e)}")
                    level.quantities.verification_quantity = 0
                    level.quantities.verification_metadata = {
                        "orders_processed": 0,
                        "days_back": 4,
                        "excluded_tag": excluded_tag,
                        "error": str(e)
                    }
                    return {
                        "store_id": level.store_id,
                        "location_id": level.location_id,
                        "quantity": 0,
                        "error": str(e)
                    }
            
            # Execute all verification queries in parallel
            verification_tasks = [verify_location(level) for level in inventory_levels]
            verification_results = await asyncio.gather(*verification_tasks, return_exceptions=True)
            
            # Process results
            total_verification_quantity = 0
            verification_details = []
            
            for result in verification_results:
                if isinstance(result, Exception):
                    logger.error(f"Verification task failed: {str(result)}")
                    continue
                    
                if result:
                    if not result.get("error"):
                        total_verification_quantity += result.get("quantity", 0)
                    verification_details.append(result)
            
            # Add verification summary
            verification_summary = {
                "total_quantity": total_verification_quantity,
                "days_back": 4,
                "excluded_tag": excluded_tag,
                "store_details": verification_details,
                "enabled": True
            }
        
        # Return consolidated result with single variant
        return InventorySearchResponse(
            barcode=barcode,
            variants=[consolidated_product] if consolidated_product else [],
            inventory_levels=inventory_levels,
            verification_summary=verification_summary
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting inventory levels: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get inventory levels: {str(e)}"
        )


@app.put("/inventory/update")
async def update_inventory_quantities(
    request: InventoryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update inventory quantities across multiple stores and locations"""
    try:
        from schemas import InventoryUpdateResponse, InventoryUpdateResult
        
        # Verify store ownership for all updates
        store_ids = list(set(update.store_id for update in request.updates))
        stores = db.query(ShopifyStore).filter(
            ShopifyStore.id.in_(store_ids),
            ShopifyStore.user_id == current_user.id,
            ShopifyStore.is_active == True
        ).all()
        
        valid_store_ids = {store.id for store in stores}
        store_map = {store.id: store for store in stores}
        
        results = []
        
        # Group updates by store
        updates_by_store = {}
        for update in request.updates:
            if update.store_id not in valid_store_ids:
                results.append(InventoryUpdateResult(
                    store_id=update.store_id,
                    location_id=update.location_id,
                    success=False,
                    error="Store not found or inactive"
                ))
                continue
            
            if update.store_id not in updates_by_store:
                updates_by_store[update.store_id] = []
            
            updates_by_store[update.store_id].append(update)
        
        # Process updates for each store
        for store_id, store_updates in updates_by_store.items():
            store = store_map[store_id]
            client = ShopifyClient(store.shop_domain, store.access_token)
            
            # Convert updates to the format expected by the client
            client_updates = []
            for update in store_updates:
                client_update = {
                    "inventory_item_id": update.inventory_item_id,
                    "location_id": update.location_id
                }
                if update.available is not None:
                    client_update["available"] = update.available
                if update.on_hand is not None:
                    client_update["on_hand"] = update.on_hand
                
                client_updates.append(client_update)
            
            try:
                # Update inventory
                update_result = await client.update_inventory_quantities(client_updates)
                
                # Process results
                for result in update_result.get("results", []):
                    results.append(InventoryUpdateResult(
                        store_id=store_id,
                        location_id=result.get("location_id"),
                        success=result.get("success", False),
                        error=result.get("error") or (", ".join(e["message"] for e in result.get("errors", [])) if result.get("errors") else None),
                        changes=result.get("adjustment_group")
                    ))
                    
            except Exception as e:
                logger.error(f"Error updating inventory for store {store.shop_name}: {str(e)}")
                for update in store_updates:
                    results.append(InventoryUpdateResult(
                        store_id=store_id,
                        location_id=update.location_id,
                        success=False,
                        error=str(e)
                    ))
        
        # Log the inventory update in order logs for audit trail
        # Since inventory updates can span multiple stores, create a log entry for each store
        successful_updates = [r for r in results if r.success]
        if successful_updates:
            # Group results by store
            store_results = {}
            for result in results:
                if result.store_id not in store_results:
                    store_results[result.store_id] = []
                store_results[result.store_id].append(result)
            
            # Create a log entry for each store
            for store_id, store_specific_results in store_results.items():
                successful_in_store = [r for r in store_specific_results if r.success]
                if successful_in_store:
                    order_log = OrderLog(
                        user_id=current_user.id,
                        store_id=store_id,
                        order_id=f"INVENTORY_UPDATE_{store_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                        order_number=f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                        action=f"inventory_update: Updated {len(successful_in_store)} location(s)",
                        status="success" if all(r.success for r in store_specific_results) else "error",
                        details=json.dumps({
                            "updates": [u.dict() for u in request.updates if u.store_id == store_id],
                            "results": [r.dict() for r in store_specific_results],
                            "summary": f"Updated inventory for {len(successful_in_store)} location(s)"
                        })
                    )
                    db.add(order_log)
            
            db.commit()
        
        return InventoryUpdateResponse(
            results=results,
            total=len(request.updates),
            successful=len(successful_updates)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating inventory: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update inventory: {str(e)}"
        )


@app.get("/inventory/history")
async def get_inventory_history(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get history of inventory operations"""
    try:
        # Query inventory-related order logs
        query = db.query(OrderLog).filter(
            OrderLog.user_id == current_user.id,
            OrderLog.action == "inventory_update"
        ).order_by(OrderLog.created_at.desc())
        
        total = query.count()
        logs = query.offset(offset).limit(limit).all()
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "history": [OrderLogResponse.from_orm(log) for log in logs]
        }
        
    except Exception as e:
        logger.error(f"Error getting inventory history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get inventory history: {str(e)}"
        )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)