"""Dashboard statistics endpoints"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import (
    User, ShopifyStore, ProcessingRule, OrderLog, Settings,
    ProcessedOrder, FraudAnalysis, FraudDetectionRule, TaskStatus,
)
from auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stores_count = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id
    ).count()
    active_stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id,
        ShopifyStore.is_active == True,
    ).count()

    rules_count = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id
    ).count()
    active_rules = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id,
        ProcessingRule.is_active == True,
    ).count()

    recent_logs = (
        db.query(OrderLog)
        .filter(OrderLog.user_id == current_user.id)
        .order_by(OrderLog.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "stores": {"total": stores_count, "active": active_stores},
        "rules": {"total": rules_count, "active": active_rules},
        "recent_activity": [
            {
                "id": log.id,
                "order_number": log.order_number,
                "action": log.action,
                "status": log.status,
                "created_at": log.created_at,
            }
            for log in recent_logs
        ],
    }


@router.get("/enhanced-stats")
async def get_enhanced_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)

    # Orders processed today
    orders_today = (
        db.query(func.count(func.distinct(OrderLog.order_id)))
        .filter(
            OrderLog.user_id == current_user.id,
            OrderLog.created_at >= today_start,
        )
        .scalar()
        or 0
    )

    # Orders per day for last 7 days
    orders_by_day = []
    for i in range(7):
        day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = (
            db.query(func.count(func.distinct(OrderLog.order_id)))
            .filter(
                OrderLog.user_id == current_user.id,
                OrderLog.created_at >= day_start,
                OrderLog.created_at < day_end,
            )
            .scalar()
            or 0
        )
        orders_by_day.append(count)
    orders_by_day.reverse()

    # Success rate
    total_orders = orders_today
    error_orders = (
        db.query(func.count(func.distinct(OrderLog.order_id)))
        .filter(
            OrderLog.user_id == current_user.id,
            OrderLog.created_at >= today_start,
            OrderLog.status == "error",
        )
        .scalar()
        or 0
    )
    success_rate = ((total_orders - error_orders) / total_orders * 100) if total_orders > 0 else 100

    # Sync info
    settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
    is_sync_enabled = settings.auto_sync_enabled if settings else False
    sync_frequency = settings.sync_frequency_minutes if settings else 10

    last_sync_time = (
        db.query(func.max(ShopifyStore.last_sync))
        .filter(ShopifyStore.user_id == current_user.id)
        .scalar()
    )
    next_sync = None
    if last_sync_time and is_sync_enabled:
        next_sync = last_sync_time + timedelta(minutes=sync_frequency)

    # Rules triggered today
    rules_triggered = (
        db.query(OrderLog.details, func.count(func.distinct(OrderLog.order_id)).label("count"))
        .filter(
            OrderLog.user_id == current_user.id,
            OrderLog.created_at >= today_start,
            OrderLog.action == "rule_applied",
        )
        .group_by(OrderLog.details)
        .all()
    )
    rules_triggered_dict = {}
    for detail, count in rules_triggered:
        if detail:
            try:
                import json
                details = json.loads(detail) if isinstance(detail, str) else detail
                rule_name = details.get("rule_name", "Unknown") if isinstance(details, dict) else "Unknown"
                rules_triggered_dict[rule_name] = count
            except Exception:
                pass

    # Store activity
    store_activity = (
        db.query(ShopifyStore.shop_name, func.count(func.distinct(OrderLog.order_id)).label("count"))
        .join(OrderLog, OrderLog.store_id == ShopifyStore.id)
        .filter(
            ShopifyStore.user_id == current_user.id,
            OrderLog.created_at >= today_start,
        )
        .group_by(ShopifyStore.shop_name)
        .all()
    )
    store_activity_dict = {name: count for name, count in store_activity}

    # Fraud stats
    fraud_analyses_today = 0
    high_risk_count = 0
    active_fraud_rules = 0
    try:
        active_fraud_rules = (
            db.query(func.count(FraudDetectionRule.id))
            .filter(
                FraudDetectionRule.user_id == current_user.id,
                FraudDetectionRule.is_active == True,
            )
            .scalar()
            or 0
        )
        if active_fraud_rules > 0:
            fraud_analyses_today = (
                db.query(func.count(FraudAnalysis.id))
                .filter(FraudAnalysis.user_id == current_user.id)
                .scalar()
                or 0
            )
    except Exception as e:
        logger.debug(f"Fraud detection query failed: {e}")

    # System health
    failed_tasks = (
        db.query(func.count(TaskStatus.id))
        .filter(
            TaskStatus.user_id == current_user.id,
            TaskStatus.status == "failed",
            TaskStatus.created_at >= seven_days_ago,
        )
        .scalar()
        or 0
    )

    # Counts
    total_processed = (
        db.query(func.count(ProcessedOrder.id))
        .join(ShopifyStore, ProcessedOrder.store_id == ShopifyStore.id)
        .filter(ShopifyStore.user_id == current_user.id)
        .scalar()
        or 0
    )
    active_stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id, ShopifyStore.is_active == True
    ).count()
    total_stores = db.query(ShopifyStore).filter(
        ShopifyStore.user_id == current_user.id
    ).count()
    active_rules = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id, ProcessingRule.is_active == True
    ).count()
    total_rules = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id
    ).count()

    # Recent activity & errors
    recent_activity = (
        db.query(OrderLog)
        .filter(OrderLog.user_id == current_user.id)
        .order_by(OrderLog.created_at.desc())
        .limit(10)
        .all()
    )
    recent_errors = (
        db.query(OrderLog)
        .filter(OrderLog.user_id == current_user.id, OrderLog.status == "error")
        .order_by(OrderLog.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "processing": {
            "orders_today": orders_today,
            "orders_last_7_days": orders_by_day,
            "success_rate": round(success_rate, 1),
            "total_processed": total_processed,
            "last_sync": last_sync_time.isoformat() + "Z" if last_sync_time else None,
            "next_sync": next_sync.isoformat() + "Z" if next_sync else None,
            "is_syncing": False,
            "sync_enabled": is_sync_enabled,
        },
        "rules": {
            "total": total_rules,
            "active": active_rules,
            "triggered_today": rules_triggered_dict,
        },
        "stores": {
            "total": total_stores,
            "active": active_stores,
            "activity": store_activity_dict,
        },
        "fraud": {
            "analyses_today": fraud_analyses_today,
            "high_risk_count": high_risk_count,
            "active_rules": active_fraud_rules,
        },
        "system": {
            "celery_status": "healthy" if failed_tasks < 5 else "degraded" if failed_tasks < 20 else "down",
            "failed_tasks": failed_tasks,
        },
        "recent_activity": [
            {
                "id": log.id,
                "order_id": log.order_id,
                "order_number": log.order_number,
                "store_name": log.store.shop_name if log.store else "Unknown",
                "action": log.action,
                "status": log.status,
                "created_at": log.created_at.isoformat() + "Z",
            }
            for log in recent_activity
        ],
        "recent_errors": [
            {
                "id": log.id,
                "order_id": log.order_id,
                "order_number": log.order_number,
                "store_name": log.store.shop_name if log.store else "Unknown",
                "action": log.action,
                "error_message": log.error_message,
                "created_at": log.created_at.isoformat() + "Z",
            }
            for log in recent_errors
        ],
    }
