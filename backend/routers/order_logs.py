"""Order logs management endpoints"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text, case

from database import get_db
from models import User, ShopifyStore, OrderLog, ProcessedOrder, TaskStatus
from auth import get_current_user
from schemas import TaskStatusResponse, FailedTasksResponse
from dependencies import _format_timestamp_with_user_timezone
from shopify_client import ShopifyClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/order-logs", tags=["Order Logs"])


@router.get("")
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
    store_ids_list = list(set(log.store_id for log in logs))
    stores = db.query(ShopifyStore).filter(ShopifyStore.id.in_(store_ids_list)).all()
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


@router.get("/all-order-ids")
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
    """Get all order IDs matching the current filters for bulk retry"""
    query = db.query(OrderLog.order_id, OrderLog.store_id).filter(
        OrderLog.user_id == current_user.id
    ).distinct()

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
            pass

    if date_to:
        try:
            to_date = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            query = query.filter(OrderLog.created_at <= to_date)
        except ValueError:
            pass

    results = query.all()

    return {
        "order_ids": [
            {"order_id": r[0], "store_id": r[1]}
            for r in results if r[0] and r[0] != "SYSTEM_RESET"
        ],
        "total": len([r for r in results if r[0] and r[0] != "SYSTEM_RESET"])
    }


@router.post("/retry")
async def retry_order_processing(
    order_ids: List[dict],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retry processing for specific orders"""
    results = []

    # Group orders by store
    orders_by_store = {}
    for order_info in order_ids:
        store_id = order_info.get("store_id")
        order_id = order_info.get("order_id")

        if not store_id or not order_id:
            results.append({"order_id": order_id, "success": False, "error": "Missing store_id or order_id"})
            continue

        if store_id not in orders_by_store:
            orders_by_store[store_id] = []
        orders_by_store[store_id].append(order_id)

    # Process each store
    for store_id, store_order_ids in orders_by_store.items():
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == current_user.id
        ).first()

        if not store:
            for oid in store_order_ids:
                results.append({"order_id": oid, "success": False, "error": "Store not found"})
            continue

        # Mark orders for reprocessing by removing from processed_orders
        for order_id in store_order_ids:
            try:
                db.query(ProcessedOrder).filter(
                    ProcessedOrder.store_id == store_id,
                    ProcessedOrder.order_id == order_id
                ).delete()
                results.append({"order_id": order_id, "success": True, "message": "Marked for reprocessing"})
            except Exception as e:
                results.append({"order_id": order_id, "success": False, "error": str(e)})

    db.commit()

    return {
        "message": f"Processed {len(results)} orders",
        "results": results,
        "success_count": len([r for r in results if r.get("success")]),
        "failure_count": len([r for r in results if not r.get("success")])
    }
