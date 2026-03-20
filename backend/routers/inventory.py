"""Inventory management endpoints"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from database import get_db
from models import User, ShopifyStore, LocationAlias, LocationMapping, OrderLog, Settings
from auth import get_current_user
from schemas import (
    InventorySearchResponse, ProductVariantInfo, InventoryLocationLevel,
    InventoryQuantities, InventoryUpdateRequest, InventoryUpdateResponse,
    InventoryUpdateResult, OrderLogResponse
)
from shopify_client import ShopifyClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get("/location-aliases")
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


@router.get("/search")
async def search_inventory_by_barcode(
    barcode: str = Query(..., description="UPC barcode to search for"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search for products by barcode across all active stores"""
    try:
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
        variant_store_map = {}

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
            inventory_levels=[]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching inventory by barcode: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search inventory: {str(e)}"
        )


@router.get("/{barcode}/levels")
async def get_inventory_levels(
    barcode: str,
    location_aliases: Optional[str] = Query(None, description="Comma-separated list of location aliases to filter by"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get inventory levels for a barcode across all stores and locations"""
    try:
        stores = db.query(ShopifyStore).filter(
            ShopifyStore.user_id == current_user.id,
            ShopifyStore.is_active == True
        ).all()

        if not stores:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active stores found"
            )

        inventory_levels_map = {}
        consolidated_product = None
        variant_ids_seen = set()
        inventory_item_ids_by_store = {}

        filter_aliases = []
        if location_aliases:
            filter_aliases = [alias.strip() for alias in location_aliases.split(",") if alias.strip()]

        location_aliases_db = db.query(LocationAlias).filter(
            LocationAlias.user_id == current_user.id,
            LocationAlias.is_active == True
        ).all()

        alias_map = {}
        allowed_locations = set()

        for alias in location_aliases_db:
            for mapping in alias.mappings:
                if mapping.is_active:
                    key = f"{mapping.store_id}:{mapping.shopify_location_id}"
                    alias_map[key] = alias.alias_name

                    if filter_aliases and alias.alias_name in filter_aliases:
                        allowed_locations.add(key)

        async def process_store(store):
            client = ShopifyClient(store.shop_domain, store.access_token)
            results = {
                "store": store,
                "variants": [],
                "inventory_levels": {},
                "error": None
            }

            try:
                variants = await client.get_product_by_barcode(barcode)
                results["variants"] = variants

                location_mappings = db.query(LocationMapping).filter(
                    LocationMapping.store_id == store.id,
                    LocationMapping.is_active == True
                ).all()

                if location_mappings and variants:
                    variant = variants[0] if variants else None
                    if variant and variant.get("id"):
                        if "_inventory_levels" in variant:
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
                            location_ids = [m.shopify_location_id for m in location_mappings]
                            inventory_data = await client.get_inventory_across_locations(variant["id"], location_ids)
                            results["inventory_levels"] = inventory_data

            except Exception as e:
                logger.error(f"Error getting inventory for store {store.shop_name}: {str(e)}")
                results["error"] = str(e)

            return results

        store_tasks = [process_store(store) for store in stores]
        store_results = await asyncio.gather(*store_tasks, return_exceptions=True)

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

                if variant_id in variant_ids_seen:
                    continue
                variant_ids_seen.add(variant_id)

                inventory_item_id = variant.get("inventoryItem", {}).get("id", "")
                if inventory_item_id:
                    inventory_item_ids_by_store[store.id] = inventory_item_id

                if not consolidated_product:
                    consolidated_product = ProductVariantInfo(
                        variant_id=variant_id,
                        title=variant.get("title", ""),
                        sku=variant.get("sku"),
                        barcode=barcode,
                        product_id=variant.get("product", {}).get("id", ""),
                        product_title=variant.get("product", {}).get("title", ""),
                        inventory_item_id=inventory_item_id
                    )

                inventory_data = result.get("inventory_levels", {})
                for location_id, level_data in inventory_data.get("inventory_levels", {}).items():
                    quantities = level_data.get("quantities", {})
                    alias_key = f"{store.id}:{location_id}"

                    inv_key = f"{store.id}:{location_id}"

                    if filter_aliases and inv_key not in allowed_locations:
                        continue

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
                        inventory_level.inventory_item_id = inventory_item_ids_by_store.get(store.id)
                        inventory_levels_map[inv_key] = inventory_level

        inventory_levels = list(inventory_levels_map.values())

        verification_enabled = os.getenv("ENABLE_INVENTORY_VERIFICATION", "true").lower() == "true"
        verification_summary = None

        if verification_enabled and consolidated_product:
            settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
            excluded_tag = settings.inventory_verification_excluded_tag if settings else None
            days_back = settings.inventory_verification_days_back if settings else 5

            store_clients = {}
            for store in stores:
                store_clients[store.id] = ShopifyClient(store.shop_domain, store.access_token)

            async def verify_location(level):
                client = store_clients.get(level.store_id)
                if not client:
                    return None

                try:
                    result = await client.get_unfulfilled_orders_for_verification(
                        barcode=barcode,
                        days_back=days_back,
                        excluded_tag=excluded_tag,
                        location_id=level.location_id
                    )

                    location_quantity = result.get("total_quantity", 0)

                    level.quantities.verification_quantity = location_quantity
                    level.quantities.verification_metadata = {
                        "orders_processed": result.get("orders_processed", 0),
                        "pages_fetched": result.get("pages_fetched", 0),
                        "execution_time": result.get("execution_time", 0),
                        "hit_time_limit": result.get("hit_time_limit", False),
                        "days_back": result.get("days_back", days_back),
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
                        "pages_fetched": 0,
                        "execution_time": 0,
                        "hit_time_limit": False,
                        "days_back": days_back,
                        "excluded_tag": excluded_tag,
                        "error": str(e)
                    }
                    return {
                        "store_id": level.store_id,
                        "location_id": level.location_id,
                        "quantity": 0,
                        "error": str(e)
                    }

            verification_tasks = [verify_location(level) for level in inventory_levels]
            verification_results = await asyncio.gather(*verification_tasks, return_exceptions=True)

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

            verification_summary = {
                "total_quantity": total_verification_quantity,
                "days_back": days_back,
                "excluded_tag": excluded_tag,
                "store_details": verification_details,
                "enabled": True
            }

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


@router.put("/update")
async def update_inventory_quantities(
    request: InventoryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update inventory quantities across multiple stores and locations"""
    try:
        store_ids = list(set(update.store_id for update in request.updates))
        stores = db.query(ShopifyStore).filter(
            ShopifyStore.id.in_(store_ids),
            ShopifyStore.user_id == current_user.id,
            ShopifyStore.is_active == True
        ).all()

        valid_store_ids = {store.id for store in stores}
        store_map = {store.id: store for store in stores}

        results = []

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

        for store_id, store_updates in updates_by_store.items():
            store = store_map[store_id]
            client = ShopifyClient(store.shop_domain, store.access_token)

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
                update_result = await client.update_inventory_quantities(client_updates)

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

        successful_updates = [r for r in results if r.success]
        if successful_updates:
            store_results = {}
            for result in results:
                if result.store_id not in store_results:
                    store_results[result.store_id] = []
                store_results[result.store_id].append(result)

            for store_id, store_specific_results in store_results.items():
                successful_in_store = [r for r in store_specific_results if r.success]
                if successful_in_store:
                    order_log = OrderLog(
                        user_id=current_user.id,
                        store_id=store_id,
                        order_id=f"INVENTORY_UPDATE_{store_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                        order_number=f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
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


@router.get("/history")
async def get_inventory_history(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get history of inventory operations"""
    try:
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
