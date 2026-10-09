"""Order logs management endpoints"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
import uuid
from sqlalchemy import func, text, case, or_, and_

from database import get_db
from models import User, ShopifyStore, OrderLog, ProcessedOrder, TaskStatus
from auth import get_current_user
from schemas import TaskStatusResponse, FailedTasksResponse, RetryOrdersRequest, OrderRiskLevelsRequest
from tasks import retry_orders_batch, create_task_status, RETRY_TASK_NAME, RETRY_CANCEL_STATUS, _retry_target_rules
from models import ExcludedSKU
from shipping_estimate_service import profit_with_shipping
from order_detail import build_order_detail, profit_snapshot
from order_risk import (order_risk, risk_level, cardholder_check, parse_filter_values, has_risk_level,
                        has_cardholder_match, save_order_risk_levels, FILTERABLE_LEVELS, CARDHOLDER_MATCHES)
from ip_location import lookup_ip_location
from dependencies import _format_timestamp_with_user_timezone
from shopify_client import ShopifyClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/order-logs", tags=["Order Logs"])

RETRY_STALE_AFTER = timedelta(hours=8)
RETRY_RECENT_WINDOW = timedelta(hours=24)


def matched_rule(rule_id: int):
    """Log rows where this rule matched: from the scheduled sync (action applied_rule_<id>)
    or from a retry/reprocess batch (action retry_processing with the rule in details)"""
    return or_(
        OrderLog.action == f"applied_rule_{rule_id}",
        and_(OrderLog.action == "retry_processing", OrderLog.details["applied_rule_id"].as_integer() == rule_id),
    )


@router.get("")
async def get_order_logs(
    store_id: Optional[int] = None,
    status: Optional[str] = None,
    action: Optional[str] = None,
    search: Optional[str] = None,
    rule_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    risk_levels: Optional[str] = None,
    cardholder_matches: Optional[str] = None,
    sort_field: Optional[str] = "latest_date",
    sort_direction: Optional[str] = "desc",
    page: int = 1,
    per_page: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(OrderLog).filter(OrderLog.user_id == current_user.id)
    levels = parse_filter_values(risk_levels, FILTERABLE_LEVELS)
    name_matches = parse_filter_values(cardholder_matches, CARDHOLDER_MATCHES)

    if store_id:
        query = query.filter(OrderLog.store_id == store_id)
    if status:
        query = query.filter(OrderLog.status == status)
    if action:
        query = query.filter(OrderLog.action.contains(action))
    if search:
        query = query.filter(OrderLog.order_number.contains(search))
    if rule_id:
        query = query.filter(matched_rule(rule_id))

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
            query = query.filter(matched_rule(rule_id))
        if parsed_date_from:
            query = query.filter(OrderLog.created_at >= parsed_date_from)
        if parsed_date_to:
            query = query.filter(OrderLog.created_at <= parsed_date_to)
        if levels:
            query = query.filter(has_risk_level(levels))
        if name_matches:
            query = query.filter(has_cardholder_match(name_matches))
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
    risk_levels: Optional[str] = None,
    cardholder_matches: Optional[str] = None,
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
        query = query.filter(matched_rule(rule_id))

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

    levels = parse_filter_values(risk_levels, FILTERABLE_LEVELS)
    if levels:
        query = query.filter(has_risk_level(levels))
    name_matches = parse_filter_values(cardholder_matches, CARDHOLDER_MATCHES)
    if name_matches:
        query = query.filter(has_cardholder_match(name_matches))

    results = query.all()

    return {
        "order_ids": [
            {"order_id": r[0], "store_id": r[1]}
            for r in results if r[0] and r[0] != "SYSTEM_RESET"
        ],
        "total": len([r for r in results if r[0] and r[0] != "SYSTEM_RESET"])
    }


@router.get("/order-detail")
async def get_order_detail(
    store_id: int,
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Order detail for the Orders page modal: order and customer info and per-line
    revenue/cost/margin loaded live from Shopify, plus the profit calculation and
    shipping estimate as recorded when a profit rule last ran on the order, falling
    back to a live calculation for orders no profit rule has evaluated"""
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")

    client = ShopifyClient(store.shop_domain, store.access_token)
    try:
        order = await client.get_order_by_id(order_id, include_fraud_data=True)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found in Shopify")
        await client.ensure_complete_line_items(order)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to load order {order_id} from {store.shop_domain}: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not load the order from Shopify: {e}")

    risk = order_risk(order)
    if risk and risk["ip"]:
        risk["ip_location"] = await lookup_ip_location(risk["ip"])

    recent_logs = db.query(OrderLog).filter(
        OrderLog.store_id == store.id,
        OrderLog.order_id == order_id
    ).order_by(OrderLog.created_at.desc()).limit(20).all()
    snapshot = profit_snapshot(recent_logs)
    if snapshot:
        return build_order_detail(order, snapshot["profit"], store, snapshot["profit_conditions"], snapshot["recorded_at"], risk)

    excluded_skus = [
        sku.sku_pattern for sku in db.query(ExcludedSKU).filter(
            ExcludedSKU.user_id == current_user.id,
            ExcludedSKU.is_active == True
        ).all()
    ]
    return build_order_detail(order, profit_with_shipping(order, store, excluded_skus, db), store, risk=risk)


@router.post("/risk-levels")
async def get_order_risk_levels(
    request: OrderRiskLevelsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Shopify's current risk level, recommendation and cardholder name check for the
    orders on the Orders page, keyed by order GID; one batched Shopify call per store.
    The results are also saved for the filters. A store that fails is logged and left
    out so its orders simply show no badge."""
    order_ids_by_store = {}
    for ref in request.orders:
        order_ids_by_store.setdefault(ref.store_id, set()).add(ref.order_id)
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.id.in_(list(order_ids_by_store)),
        ShopifyStore.user_id == current_user.id
    ).all() if order_ids_by_store else []

    levels = {}
    for store in stores:
        client = ShopifyClient(store.shop_domain, store.access_token)
        try:
            orders = await client.get_order_risk_data(sorted(order_ids_by_store[store.id]))
        except Exception as e:
            logger.warning(f"Could not load order risk levels from {store.shop_domain}: {e}")
            continue
        for order_id, order in orders.items():
            risk = order.get("risk") or {}
            cardholder = cardholder_check(order)
            levels[order_id] = {
                "level": risk_level(risk),
                "recommendation": risk.get("recommendation"),
                "cardholder_match": cardholder["status"] if cardholder else None,
                "card_names": cardholder["card_names"] if cardholder else [],
            }
        try:
            save_order_risk_levels(db, store.id, order_ids_by_store[store.id], orders)
        except Exception as e:
            db.rollback()
            logger.warning(f"Could not save order risk levels for {store.shop_domain}: {e}")
    return levels


def retry_batch_view(task: TaskStatus) -> dict:
    result = task.result or {}
    return {
        "task_id": task.task_id,
        "status": task.status,
        "rule_id": result.get("rule_id"),
        "rule_name": result.get("rule_name"),
        "total": result.get("total", 0),
        "processed": result.get("processed", 0),
        "matched": result.get("matched", 0),
        "skipped": result.get("skipped", 0),
        "failed": result.get("failed", 0),
        "current_order": result.get("current_order"),
        "last_order": result.get("last_order"),
        "cancelled": bool(result.get("cancelled")),
        "error": result.get("error") or task.error_message,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.post("/retry")
async def retry_order_processing(
    request: RetryOrdersRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Queue a batch that re-runs the user's active rules (or one rule) on the given
    orders. Progress is read from GET /order-logs/retry/status; each order's outcome
    is written to the order log as it completes."""
    try:
        rules = _retry_target_rules(request.rule_id, current_user.id, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    task_id = str(uuid.uuid4())
    rule_name = rules[0].name if request.rule_id else None
    create_task_status(task_id, RETRY_TASK_NAME, status="running", user_id=current_user.id)
    task = db.query(TaskStatus).filter(TaskStatus.task_id == task_id).first()
    task.result = {
        "rule_id": request.rule_id, "rule_name": rule_name, "total": len(request.order_ids),
        "processed": 0, "matched": 0, "skipped": 0, "failed": 0, "current_order": None, "cancelled": False,
    }
    db.commit()
    try:
        retry_orders_batch.delay(current_user.id, request.order_ids, request.rule_id, task_id)
    except Exception as e:
        logger.error(f"Could not queue retry batch for user {current_user.id}: {e}", exc_info=True)
        task.status = "failed"
        task.error_message = f"Could not queue the batch: {e}"
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The background worker is not reachable; the batch was not started")
    return {
        "task_id": task_id,
        "total": len(request.order_ids),
        "rule_name": rule_name,
        "message": f"Reprocessing {len(request.order_ids)} orders with "
                   f"{'rule ' + repr(rule_name) if rule_name else 'all active rules'}",
    }


@router.get("/retry/status")
async def get_retry_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """The user's running reprocess batches plus the ones finished in the last day"""
    now = datetime.now(timezone.utc)
    batches = db.query(TaskStatus).filter(
        TaskStatus.user_id == current_user.id,
        TaskStatus.task_name == RETRY_TASK_NAME,
    ).order_by(TaskStatus.created_at.desc()).limit(50).all()

    running, recent = [], []
    for task in batches:
        if task.status in ("running", RETRY_CANCEL_STATUS):
            started = task.started_at or task.created_at
            if started and now - started.replace(tzinfo=started.tzinfo or timezone.utc) > RETRY_STALE_AFTER:
                task.status = "failed"
                task.error_message = "Batch stopped reporting progress"
                task.completed_at = now
                db.commit()
            else:
                running.append(retry_batch_view(task))
                continue
        finished = task.completed_at or task.created_at
        if len(recent) < 5 and finished and now - finished.replace(tzinfo=finished.tzinfo or timezone.utc) <= RETRY_RECENT_WINDOW:
            recent.append(retry_batch_view(task))
    return {"running": running, "recent": recent}


@router.post("/retry/{task_id}/cancel")
async def cancel_retry_batch(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stop a running batch after the order it is on; orders already processed keep their results"""
    task = db.query(TaskStatus).filter(
        TaskStatus.task_id == task_id,
        TaskStatus.user_id == current_user.id,
        TaskStatus.task_name == RETRY_TASK_NAME,
    ).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    if task.status == "running":
        task.status = RETRY_CANCEL_STATUS
        db.commit()
    return retry_batch_view(task)
