from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date
import uvicorn
import os
import logging
import asyncio
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from database import engine, get_db, create_tables
from models import User, ShopifyStore, ProcessingRule, OrderLog, Settings, ProcessedOrder, LocationAlias, LocationMapping, OutOfStockIncident
from auth import get_current_user, create_access_token, verify_password, get_password_hash
from schemas import (
    UserCreate, UserLogin, TokenResponse, ShopifyStoreCreate, RuleCreate, SettingsUpdate, SettingsResponse, OrderLogQuery,
    LocationAliasCreate, LocationAliasUpdate, LocationAliasResponse, LocationMappingCreate, LocationMappingUpdate, 
    LocationMappingResponse, StoreLocationResponse
)
from shopify_client import ShopifyClient
from tasks import test_celery_connection, process_store_orders, process_all_orders

security = HTTPBearer()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Creating database tables...")
    create_tables()
    print("Database tables created successfully")
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
        
        # Group by location for summary
        location_summary = {}
        for log in oos_logs:
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
            "total_oos_orders": len(oos_logs),
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
                for log in oos_logs
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
        
        # Get aggregated product data
        product_aggregates = db.query(
            OutOfStockIncident.product_id,
            OutOfStockIncident.variant_id,
            OutOfStockIncident.product_title,
            OutOfStockIncident.variant_title,
            OutOfStockIncident.sku,
            OutOfStockIncident.vendor,
            OutOfStockIncident.product_type,
            func.count(OutOfStockIncident.id).label('total_incidents'),
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
        ).order_by(desc('total_incidents')).all()
        
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
                incident_frequency = round(product.total_incidents / days_span, 2)
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
                "total_incidents": product.total_incidents,
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)