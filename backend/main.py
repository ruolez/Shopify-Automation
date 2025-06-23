from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
import uvicorn
import os
from contextlib import asynccontextmanager

from database import engine, get_db, create_tables
from models import User, ShopifyStore, ProcessingRule, OrderLog, Settings, ProcessedOrder
from auth import get_current_user, create_access_token, verify_password, get_password_hash
from schemas import UserCreate, UserLogin, TokenResponse, ShopifyStoreCreate, RuleCreate, SettingsUpdate, SettingsResponse, OrderLogQuery
from shopify_client import ShopifyClient
from tasks import test_celery_connection, process_store_orders, process_all_orders

security = HTTPBearer()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_tables()
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost"],
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
@app.post("/rules")
async def create_rule(
    rule_data: RuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_rule = ProcessingRule(
        user_id=current_user.id,
        name=rule_data.name,
        description=rule_data.description,
        conditions=[condition.dict() for condition in rule_data.conditions],
        actions=[action.dict() for action in rule_data.actions],
        priority=rule_data.priority,
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
        "is_active": db_rule.is_active,
        "created_at": db_rule.created_at
    }

@app.get("/rules")
async def get_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rules = db.query(ProcessingRule).filter(ProcessingRule.user_id == current_user.id).all()
    return [
        {
            "id": rule.id,
            "name": rule.name,
            "description": rule.description,
            "conditions": rule.conditions,
            "actions": rule.actions,
            "priority": rule.priority,
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
    rule.conditions = [condition.dict() for condition in rule_data.conditions]
    rule.actions = [action.dict() for action in rule_data.actions]
    rule.priority = rule_data.priority
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
    
    for field, value in settings_data.dict().items():
        setattr(settings, field, value)
    
    db.commit()
    db.refresh(settings)
    return settings

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
                "created_at": log.created_at
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)