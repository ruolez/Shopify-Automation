"""Location aliases and reports endpoints"""
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, ShopifyStore, OrderLog, LocationAlias, LocationMapping, OutOfStockIncident
from auth import get_current_user
from schemas import (
    LocationAliasCreate, LocationAliasUpdate, LocationAliasResponse,
    LocationMappingCreate, LocationMappingUpdate, LocationMappingResponse,
    StoreLocationResponse
)
from shopify_client import ShopifyClient
from db_utils import get_date_trunc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Locations"])


@router.get("/locations")
async def get_all_locations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all locations across all stores for the current user"""
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id,
        ShopifyStore.is_active == True
    ).all()

    all_locations = []
    for store in stores:
        client = ShopifyClient(store.shop_domain, store.access_token)
        try:
            locations = await client.get_locations()
            for loc in locations:
                all_locations.append({
                    "store_id": store.id,
                    "store_name": store.shop_name,
                    "location_id": loc["id"],
                    "location_name": loc["name"]
                })
        except Exception as e:
            logger.error(f"Failed to get locations for store {store.shop_name}: {str(e)}")

    return {"locations": all_locations}


@router.get("/location-aliases", response_model=list[LocationAliasResponse])
async def get_location_aliases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all location aliases for the current user with their mappings"""
    aliases = db.query(LocationAlias).filter(
        LocationAlias.user_id == current_user.id,
        LocationAlias.is_active == True
    ).all()

    result = []
    for alias in aliases:
        alias_dict = {
            "id": alias.id,
            "alias_name": alias.alias_name,
            "description": alias.description,
            "is_active": alias.is_active,
            "created_at": alias.created_at,
            "updated_at": alias.updated_at,
            "mappings": []
        }

        # Get mappings for this alias
        for mapping in alias.mappings:
            if mapping.is_active:
                # Get store info
                store = db.query(ShopifyStore).filter(
                    ShopifyStore.id == mapping.store_id
                ).first()
                alias_dict["mappings"].append({
                    "id": mapping.id,
                    "alias_id": mapping.alias_id,
                    "store_id": mapping.store_id,
                    "store_name": store.shop_name if store else "Unknown",
                    "shopify_location_id": mapping.shopify_location_id,
                    "shopify_location_name": mapping.shopify_location_name,
                    "is_active": mapping.is_active,
                    "created_at": mapping.created_at
                })

        result.append(alias_dict)

    return result


@router.post("/location-aliases", response_model=LocationAliasResponse)
async def create_location_alias(
    alias_data: LocationAliasCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new location alias"""
    # Check if alias name already exists
    existing = db.query(LocationAlias).filter(
        LocationAlias.user_id == current_user.id,
        LocationAlias.alias_name == alias_data.alias_name,
        LocationAlias.is_active == True
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Location alias with this name already exists"
        )

    db_alias = LocationAlias(
        user_id=current_user.id,
        alias_name=alias_data.alias_name
    )
    db.add(db_alias)
    db.commit()
    db.refresh(db_alias)

    return {
        "id": db_alias.id,
        "user_id": db_alias.user_id,
        "alias_name": db_alias.alias_name,
        "is_active": db_alias.is_active,
        "created_at": db_alias.created_at,
        "updated_at": db_alias.updated_at,
        "mappings": []
    }


@router.put("/location-aliases/{alias_id}", response_model=LocationAliasResponse)
async def update_location_alias(
    alias_id: int,
    alias_data: LocationAliasUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a location alias"""
    db_alias = db.query(LocationAlias).filter(
        LocationAlias.id == alias_id,
        LocationAlias.user_id == current_user.id
    ).first()

    if not db_alias:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location alias not found"
        )

    # Check if new name conflicts with existing
    if alias_data.alias_name and alias_data.alias_name != db_alias.alias_name:
        existing = db.query(LocationAlias).filter(
            LocationAlias.user_id == current_user.id,
            LocationAlias.alias_name == alias_data.alias_name,
            LocationAlias.is_active == True,
            LocationAlias.id != alias_id
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Location alias with this name already exists"
            )

    for field, value in alias_data.dict(exclude_unset=True).items():
        setattr(db_alias, field, value)

    db.commit()
    db.refresh(db_alias)

    # Get mappings for response
    mappings = []
    for mapping in db_alias.mappings:
        if mapping.is_active:
            store = db.query(ShopifyStore).filter(
                ShopifyStore.id == mapping.store_id
            ).first()
            mappings.append({
                "id": mapping.id,
                "alias_id": mapping.alias_id,
                "store_id": mapping.store_id,
                "store_name": store.shop_name if store else "Unknown",
                "shopify_location_id": mapping.shopify_location_id,
                "shopify_location_name": mapping.shopify_location_name,
                "is_active": mapping.is_active,
                "created_at": mapping.created_at
            })

    return {
        "id": db_alias.id,
        "user_id": db_alias.user_id,
        "alias_name": db_alias.alias_name,
        "is_active": db_alias.is_active,
        "created_at": db_alias.created_at,
        "updated_at": db_alias.updated_at,
        "mappings": mappings
    }


@router.delete("/location-aliases/{alias_id}")
async def delete_location_alias(
    alias_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a location alias (soft delete)"""
    db_alias = db.query(LocationAlias).filter(
        LocationAlias.id == alias_id,
        LocationAlias.user_id == current_user.id
    ).first()

    if not db_alias:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location alias not found"
        )

    db_alias.is_active = False
    db.commit()

    return {"message": "Location alias deleted successfully"}


@router.get("/location-aliases/{alias_id}/mappings", response_model=list[LocationMappingResponse])
async def get_alias_mappings(
    alias_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all mappings for a specific location alias"""
    db_alias = db.query(LocationAlias).filter(
        LocationAlias.id == alias_id,
        LocationAlias.user_id == current_user.id
    ).first()

    if not db_alias:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location alias not found"
        )

    result = []
    for mapping in db_alias.mappings:
        if mapping.is_active:
            store = db.query(ShopifyStore).filter(
                ShopifyStore.id == mapping.store_id
            ).first()
            result.append({
                "id": mapping.id,
                "alias_id": mapping.alias_id,
                "store_id": mapping.store_id,
                "store_name": store.shop_name if store else "Unknown",
                "shopify_location_id": mapping.shopify_location_id,
                "shopify_location_name": mapping.shopify_location_name,
                "is_active": mapping.is_active,
                "created_at": mapping.created_at
            })

    return result


@router.post("/location-aliases/{alias_id}/mappings", response_model=LocationMappingResponse)
async def create_alias_mapping(
    alias_id: int,
    mapping_data: LocationMappingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new location mapping for an alias"""
    # Verify alias exists and belongs to user
    db_alias = db.query(LocationAlias).filter(
        LocationAlias.id == alias_id,
        LocationAlias.user_id == current_user.id,
        LocationAlias.is_active == True
    ).first()

    if not db_alias:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location alias not found"
        )

    # Verify store belongs to user
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == mapping_data.store_id,
        ShopifyStore.user_id == current_user.id
    ).first()

    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found"
        )

    # Check if mapping already exists
    existing = db.query(LocationMapping).filter(
        LocationMapping.alias_id == alias_id,
        LocationMapping.store_id == mapping_data.store_id,
        LocationMapping.shopify_location_id == mapping_data.shopify_location_id,
        LocationMapping.is_active == True
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This location is already mapped to this alias"
        )

    db_mapping = LocationMapping(
        alias_id=alias_id,
        store_id=mapping_data.store_id,
        shopify_location_id=mapping_data.shopify_location_id,
        shopify_location_name=mapping_data.shopify_location_name
    )
    db.add(db_mapping)
    db.commit()
    db.refresh(db_mapping)

    return {
        "id": db_mapping.id,
        "alias_id": db_mapping.alias_id,
        "store_id": db_mapping.store_id,
        "store_name": store.shop_name,
        "shopify_location_id": db_mapping.shopify_location_id,
        "shopify_location_name": db_mapping.shopify_location_name,
        "is_active": db_mapping.is_active,
        "created_at": db_mapping.created_at
    }


@router.delete("/location-mappings/{mapping_id}")
async def delete_alias_mapping(
    mapping_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a location mapping (soft delete)"""
    # Get the mapping and verify ownership through alias
    db_mapping = db.query(LocationMapping).join(LocationAlias).filter(
        LocationMapping.id == mapping_id,
        LocationAlias.user_id == current_user.id
    ).first()

    if not db_mapping:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location mapping not found"
        )

    db_mapping.is_active = False
    db.commit()

    return {"message": "Location mapping deleted successfully"}


@router.get("/store-locations", response_model=list[StoreLocationResponse])
async def get_store_locations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all locations for all stores owned by the current user"""
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id,
        ShopifyStore.is_active == True
    ).all()

    result = []
    for store in stores:
        client = ShopifyClient(store.shop_domain, store.access_token)
        try:
            locations = await client.get_locations()
            # Return data matching StoreLocationResponse schema
            result.append({
                "store_id": store.id,
                "store_name": store.shop_name,
                "store_domain": store.shop_domain,
                "locations": [{"id": loc["id"], "name": loc["name"]} for loc in locations]
            })
        except Exception as e:
            logger.error(f"Failed to get locations for store {store.shop_name}: {str(e)}")

    return result


# Reports endpoints
@router.get("/reports/fulfillment-errors")
async def get_fulfillment_errors_report(
    days: int = Query(default=7, ge=1, le=30),
    store_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get fulfillment errors report"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    query = db.query(OrderLog).filter(
        OrderLog.user_id == current_user.id,
        OrderLog.created_at >= cutoff_date,
        OrderLog.status == "error",
        OrderLog.action.contains("fulfillment")
    )

    if store_id:
        query = query.filter(OrderLog.store_id == store_id)

    errors = query.order_by(OrderLog.created_at.desc()).all()

    # Get store names
    store_ids_list = list(set(e.store_id for e in errors))
    stores = db.query(ShopifyStore).filter(ShopifyStore.id.in_(store_ids_list)).all()
    store_map = {s.id: s.shop_name for s in stores}

    # Group by error type
    error_groups = {}
    for error in errors:
        error_type = error.error_message or "Unknown Error"
        if error_type not in error_groups:
            error_groups[error_type] = []
        error_groups[error_type].append({
            "id": error.id,
            "order_number": error.order_number,
            "store_name": store_map.get(error.store_id, "Unknown"),
            "created_at": error.created_at.isoformat() + "Z" if error.created_at else None,
            "details": error.details
        })

    return {
        "period_days": days,
        "total_errors": len(errors),
        "error_groups": error_groups
    }


@router.get("/reports/oos-orders")
async def get_oos_orders_report(
    days: int = Query(default=7, ge=1, le=30),
    store_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get out-of-stock orders report"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    query = db.query(OutOfStockIncident).filter(
        OutOfStockIncident.user_id == current_user.id,
        OutOfStockIncident.created_at >= cutoff_date
    )

    if store_id:
        query = query.filter(OutOfStockIncident.store_id == store_id)

    incidents = query.order_by(OutOfStockIncident.created_at.desc()).all()

    # Get store names
    store_ids_list = list(set(i.store_id for i in incidents))
    stores = db.query(ShopifyStore).filter(ShopifyStore.id.in_(store_ids_list)).all()
    store_map = {s.id: s.shop_name for s in stores}

    # Group by day using Python
    daily_counts = {}
    for incident in incidents:
        if incident.created_at:
            date_key = incident.created_at.strftime('%Y-%m-%d')
            if date_key not in daily_counts:
                daily_counts[date_key] = 0
            daily_counts[date_key] += 1

    return {
        "period_days": days,
        "total_incidents": len(incidents),
        "daily_counts": daily_counts,
        "incidents": [
            {
                "id": incident.id,
                "order_number": incident.order_number,
                "store_name": store_map.get(incident.store_id, "Unknown"),
                "product_sku": incident.product_sku,
                "product_title": incident.product_title,
                "requested_quantity": incident.requested_quantity,
                "created_at": incident.created_at.isoformat() + "Z" if incident.created_at else None
            }
            for incident in incidents[:50]  # Limit to 50 most recent
        ]
    }


@router.get("/reports/oos-products")
async def get_oos_products_report(
    days: int = Query(default=7, ge=1, le=30),
    store_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get out-of-stock products report (grouped by product)"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    query = db.query(
        OutOfStockIncident.product_sku,
        OutOfStockIncident.product_title,
        func.count(OutOfStockIncident.id).label('incident_count'),
        func.sum(OutOfStockIncident.requested_quantity).label('total_requested')
    ).filter(
        OutOfStockIncident.user_id == current_user.id,
        OutOfStockIncident.created_at >= cutoff_date
    )

    if store_id:
        query = query.filter(OutOfStockIncident.store_id == store_id)

    products = query.group_by(
        OutOfStockIncident.product_sku,
        OutOfStockIncident.product_title
    ).order_by(func.count(OutOfStockIncident.id).desc()).all()

    return {
        "period_days": days,
        "total_products": len(products),
        "products": [
            {
                "product_sku": p[0],
                "product_title": p[1],
                "incident_count": p[2],
                "total_requested": p[3]
            }
            for p in products
        ]
    }


@router.post("/reports/oos-products/analyze")
async def analyze_oos_products(
    days: int = Query(default=7, ge=1, le=30),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Analyze OOS products and check current inventory"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    # Get OOS products grouped by SKU
    products = db.query(
        OutOfStockIncident.product_sku,
        OutOfStockIncident.product_title,
        func.count(OutOfStockIncident.id).label('incident_count'),
        func.sum(OutOfStockIncident.requested_quantity).label('total_requested')
    ).filter(
        OutOfStockIncident.user_id == current_user.id,
        OutOfStockIncident.created_at >= cutoff_date
    ).group_by(
        OutOfStockIncident.product_sku,
        OutOfStockIncident.product_title
    ).order_by(func.count(OutOfStockIncident.id).desc()).limit(20).all()

    # Get stores for inventory check
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id,
        ShopifyStore.is_active == True
    ).all()

    results = []
    for product in products:
        sku = product[0]
        result = {
            "product_sku": sku,
            "product_title": product[1],
            "incident_count": product[2],
            "total_requested": product[3],
            "current_inventory": []
        }

        # Check inventory in each store
        for store in stores:
            client = ShopifyClient(store.shop_domain, store.access_token)
            try:
                variants = await client.get_product_by_sku(sku)
                for variant in variants:
                    inventory_item = variant.get("inventoryItem", {})
                    inventory_levels = inventory_item.get("inventoryLevels", {}).get("edges", [])
                    for level in inventory_levels:
                        node = level.get("node", {})
                        quantities = node.get("quantities", [])
                        available = 0
                        for q in quantities:
                            if q.get("name") == "available":
                                available = q.get("quantity", 0)
                                break
                        location = node.get("location", {})
                        result["current_inventory"].append({
                            "store_name": store.shop_name,
                            "location_name": location.get("name", "Unknown"),
                            "available": available
                        })
            except Exception as e:
                logger.error(f"Failed to check inventory for SKU {sku} in {store.shop_name}: {str(e)}")

        results.append(result)

    return {
        "period_days": days,
        "products": results
    }
