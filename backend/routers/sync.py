"""Sync and debug endpoints"""
import logging
import os
import traceback
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from rate_limiting import limiter, SYNC_LIMIT
from models import User, ShopifyStore, ProcessingRule, OrderLog, Settings, ProcessedOrder, TaskStatus, FraudAnalysis, ExcludedSKU
from auth import get_current_user
from shopify_client import ShopifyClient
from tasks import process_store_orders, process_all_orders
from dependencies import _format_timestamp_with_user_timezone
from schemas import TaskStatusResponse, FailedTasksResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sync"])


@router.post("/sync/store/{store_id}")
async def sync_store(
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

    # Trigger async processing
    task = process_store_orders.delay(current_user.id, store.id)
    return {"message": "Sync started", "task_id": task.id}


@router.post("/sync/all")
async def sync_all_stores(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Trigger async processing for all user's stores
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id,
        ShopifyStore.is_active == True
    ).all()

    if not stores:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active stores found"
        )

    tasks = []
    for store in stores:
        task = process_store_orders.delay(current_user.id, store.id)
        tasks.append({"store_id": store.id, "store_domain": store.shop_domain, "task_id": task.id})

    return {"message": f"Sync started for {len(tasks)} stores", "tasks": tasks}


# Debug endpoints
@router.get("/debug/locations/{store_id}")
async def debug_locations(
    store_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if os.getenv("ENVIRONMENT", "development") == "production":
        raise HTTPException(status_code=404, detail="Not found")
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
            "store": store.shop_name,
            "locations": locations
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/debug/query-costs/{store_id}")
async def debug_query_costs(
    store_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if os.getenv("ENVIRONMENT", "development") == "production":
        raise HTTPException(status_code=404, detail="Not found")
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()

    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    client = ShopifyClient(store.shop_domain, store.access_token)
    return {"query_costs": client.query_costs}


@router.get("/debug/orders/{store_id}")
async def debug_orders(
    store_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if os.getenv("ENVIRONMENT", "development") == "production":
        raise HTTPException(status_code=404, detail="Not found")
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
        orders = await client.get_recent_orders(limit=5)
        return {
            "store": store.shop_name,
            "order_count": len(orders),
            "orders": [
                {
                    "id": order["id"],
                    "name": order.get("name"),
                    "fulfillment_status": order.get("displayFulfillmentStatus"),
                    "financial_status": order.get("displayFinancialStatus"),
                    "tags": order.get("tags", []),
                    "line_items_count": len(order.get("lineItems", {}).get("edges", [])),
                    "shipping_address": order.get("shippingAddress")
                }
                for order in orders
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/debug/rules/{rule_id}")
async def debug_rule(
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

    from rule_engine import RuleEngine
    engine = RuleEngine()

    return {
        "rule": {
            "id": rule.id,
            "name": rule.name,
            "conditions": rule.conditions,
            "actions": rule.actions
        },
        "condition_analysis": {
            "conditions": rule.conditions,
            "parsed_conditions": engine.get_available_fields()
        }
    }


@router.post("/debug/test-rule/{rule_id}/{store_id}")
async def debug_test_rule(
    rule_id: int,
    store_id: int,
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

    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()

    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found"
        )

    from rule_engine import RuleEngine
    from shipping_estimate_service import profit_with_shipping
    engine = RuleEngine()

    excluded_sku_patterns = [
        sku.sku_pattern
        for sku in db.query(ExcludedSKU).filter(
            ExcludedSKU.user_id == current_user.id,
            ExcludedSKU.is_active == True
        ).all()
    ]

    client = ShopifyClient(store.shop_domain, store.access_token)
    try:
        orders_data = await client.get_orders(limit=10)
        orders = [edge["node"] for edge in orders_data.get("edges", [])]
        for order in orders:
            await client.ensure_complete_line_items(order)
        results = []

        for order in orders:
            results.append({
                "order_name": order.get("name"),
                "order_id": order.get("id"),
                "matched": engine.evaluate_rule(rule, order, excluded_sku_patterns, store),
                "profit": profit_with_shipping(order, store, excluded_sku_patterns, db),
            })

        return {
            "rule": rule.name,
            "store": store.shop_name,
            "orders_tested": len(orders),
            "matched_count": sum(1 for r in results if r["matched"]),
            "results": results
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/debug/move-fulfillment")
async def debug_move_fulfillment(
    store_id: int,
    order_id: str,
    target_location_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug endpoint to test fulfillment location move"""
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
        # Get current fulfillment orders
        fulfillment_orders = await client.get_fulfillment_orders_for_order(order_id)

        if not fulfillment_orders:
            return {
                "success": False,
                "error": "No fulfillment orders found for this order",
                "order_id": order_id
            }

        # Move each fulfillment order to the target location
        results = []
        for fo in fulfillment_orders:
            fo_id = fo["id"]
            current_location = fo.get("assignedLocation", {}).get("location", {})

            if current_location.get("id") == target_location_id:
                results.append({
                    "fulfillment_order_id": fo_id,
                    "status": "skipped",
                    "reason": "Already at target location"
                })
                continue

            try:
                move_result = await client.move_fulfillment_order(fo_id, target_location_id)
                results.append({
                    "fulfillment_order_id": fo_id,
                    "status": "success" if move_result["success"] else "failed",
                    "from_location": current_location.get("name"),
                    "to_location": target_location_id,
                    "errors": move_result.get("errors")
                })
            except Exception as e:
                results.append({
                    "fulfillment_order_id": fo_id,
                    "status": "error",
                    "error": str(e)
                })

        return {
            "order_id": order_id,
            "target_location_id": target_location_id,
            "fulfillment_orders_processed": len(results),
            "results": results
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "order_id": order_id
        }


@router.get("/debug/order-data/{store_id}")
async def debug_order_data(
    store_id: int,
    order_name: str = Query(..., description="Order number to look up (e.g., TS8270741)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug endpoint to get raw order data for analysis"""
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
        # Get detailed order data including fraud info
        fraud_data = await client.get_order_fraud_data(order_name)

        if not fraud_data:
            return {
                "found": False,
                "order_name": order_name,
                "error": "Order not found"
            }

        return {
            "found": True,
            "order_name": order_name,
            "store": store.shop_name,
            "order_data": fraud_data
        }

    except Exception as e:
        logger.error(f"Debug order data error: {str(e)}")
        return {
            "found": False,
            "order_name": order_name,
            "error": str(e)
        }


@router.get("/debug/task-status")
async def debug_task_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug endpoint to check task status"""
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


@router.get("/debug/fulfillment-orders-raw")
async def debug_fulfillment_orders_raw(
    order_id: str = Query(..., description="Order ID to debug"),
    store_id: int = Query(..., description="Store ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug endpoint to see raw GraphQL response for fulfillment orders"""
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
            raw_result = await client.execute_graphql(query, variables)
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


@router.get("/debug/fraud-order/{analysis_id}")
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
@router.get("/task-status/failed", response_model=FailedTasksResponse)
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


@router.get("/task-status/{task_id}", response_model=TaskStatusResponse)
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


@router.delete("/task-status/{task_id}")
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
