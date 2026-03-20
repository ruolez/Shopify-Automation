"""Store management endpoints"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta, date, timezone

from database import get_db
from models import User, ShopifyStore, ProcessingRule, OrderLog, ProcessedOrder
from auth import get_current_user
from schemas import ShopifyStoreCreate
from shopify_client import ShopifyClient
from db_utils import get_date_trunc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stores", tags=["Stores"])


@router.post("")
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


@router.get("")
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


@router.delete("/{store_id}")
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


@router.put("/{store_id}/toggle-active")
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


@router.get("/{store_id}/locations")
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

    client = ShopifyClient(store.shop_domain, store.access_token)
    try:
        locations = await client.get_locations()
        return {
            "store_id": store.id,
            "store_name": store.shop_name,
            "locations": locations
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch locations: {str(e)}"
        )


# Dashboard endpoints that belong to stores context
@router.get("", include_in_schema=False)
async def dashboard_stats_redirect():
    """Redirect to prevent collision with /dashboard/stats"""
    pass
