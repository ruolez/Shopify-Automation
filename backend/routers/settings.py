"""Settings management endpoints"""
import os
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from database import get_db
from rate_limiting import limiter, TRIGGER_LIMIT
from models import (
    User, ShopifyStore, ProcessingRule, OrderLog, Settings, ProcessedOrder,
    OutOfStockIncident, ExcludedSKU, FraudAnalysis, FraudDetectionRule, TaskStatus
)
from auth import get_current_user
from schemas import (
    SettingsUpdate, SettingsResponse, ExcludedSKUCreate, ExcludedSKUUpdate, ExcludedSKUResponse
)
from dependencies import _format_timestamp_with_user_timezone
from tasks import trigger_fraud_analysis_all_recent, reprocess_fraud_rules_recent
import database_utils
from db_utils import get_db_type

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()

    if not settings:
        settings = Settings(user_id=current_user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)

    return settings


@router.put("", response_model=SettingsResponse)
async def update_settings(
    settings_data: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()

    if not settings:
        settings = Settings(user_id=current_user.id)
        db.add(settings)

    for field, value in settings_data.dict(exclude_unset=True).items():
        setattr(settings, field, value)

    db.commit()
    db.refresh(settings)
    return settings


@router.post("/reset-data")
async def reset_user_data(
    reset_order_logs: bool = True,
    reset_processed_orders: bool = True,
    reset_oos_incidents: bool = True,
    reset_fraud_analyses: bool = False,
    reset_archived_fraud_analyses: bool = False,
    reset_task_status: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reset various data types for the current user"""
    try:
        deleted_counts = {}

        # Get user's store IDs
        store_ids = db.query(ShopifyStore.id).filter(
            ShopifyStore.user_id == current_user.id
        ).all()
        store_ids = [s[0] for s in store_ids]

        # Delete order logs
        if reset_order_logs:
            count = db.query(OrderLog).filter(OrderLog.user_id == current_user.id).count()
            db.query(OrderLog).filter(OrderLog.user_id == current_user.id).delete()
            deleted_counts["order_logs"] = count
            logger.info(f"Deleted {count} order logs for user {current_user.id}")

        # Delete processed orders
        if reset_processed_orders and store_ids:
            count = db.query(ProcessedOrder).filter(
                ProcessedOrder.store_id.in_(store_ids)
            ).count()
            db.query(ProcessedOrder).filter(
                ProcessedOrder.store_id.in_(store_ids)
            ).delete()
            deleted_counts["processed_orders"] = count
            logger.info(f"Deleted {count} processed orders for user {current_user.id}")

        # Delete out-of-stock incidents
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
                # Check if the archive table exists first
                table_exists = db.execute(
                    text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'fraud_analyses_archive')")
                ).scalar()

                if table_exists:
                    result = db.execute(
                        text("DELETE FROM fraud_analyses_archive WHERE user_id = :user_id"),
                        {"user_id": current_user.id}
                    )
                    count = result.rowcount
                    deleted_counts["archived_fraud_analyses"] = count
                    logger.info(f"Deleted {count} archived fraud analyses for user {current_user.id}")
                else:
                    deleted_counts["archived_fraud_analyses"] = 0
                    logger.debug("fraud_analyses_archive table does not exist")
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


@router.get("/data-stats")
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

    # Count archived fraud analyses - check if table exists first
    archived_fraud_count = 0
    try:
        # Check if the archive table exists
        table_exists = db.execute(
            text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'fraud_analyses_archive')")
        ).scalar()

        if table_exists:
            result = db.execute(
                text("SELECT COUNT(*) FROM fraud_analyses_archive WHERE user_id = :user_id"),
                {"user_id": current_user.id}
            ).scalar()
            archived_fraud_count = result or 0
        else:
            logger.debug("fraud_analyses_archive table does not exist")
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


@router.get("/timezones")
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


@router.get("/inventory-verification")
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
        "days_back": settings.inventory_verification_days_back or 5,
        "enabled": os.getenv("ENABLE_INVENTORY_VERIFICATION", "true").lower() == "true"
    }


@router.put("/inventory-verification")
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

    # Update days_back if provided
    if "days_back" in data:
        days_back = data.get("days_back")
        # Ensure it's a valid integer between 1 and 30
        if isinstance(days_back, int) and 1 <= days_back <= 30:
            settings.inventory_verification_days_back = days_back

    db.commit()
    db.refresh(settings)

    return {
        "excluded_tag": settings.inventory_verification_excluded_tag,
        "days_back": settings.inventory_verification_days_back or 5,
        "enabled": os.getenv("ENABLE_INVENTORY_VERIFICATION", "true").lower() == "true"
    }


@router.get("/date-formats")
async def get_date_formats(
    current_user: User = Depends(get_current_user)
):
    """Get list of available date formats with examples"""
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


@router.get("/excluded-skus", response_model=List[ExcludedSKUResponse])
async def get_excluded_skus(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all excluded SKUs for the current user"""
    skus = db.query(ExcludedSKU).filter(
        ExcludedSKU.user_id == current_user.id
    ).order_by(ExcludedSKU.created_at.desc()).all()
    return skus


@router.post("/excluded-skus", response_model=ExcludedSKUResponse)
async def create_excluded_sku(
    sku_data: ExcludedSKUCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a new excluded SKU"""
    # Check if SKU already exists
    existing = db.query(ExcludedSKU).filter(
        ExcludedSKU.user_id == current_user.id,
        ExcludedSKU.sku == sku_data.sku
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SKU already exists in exclusion list"
        )

    db_sku = ExcludedSKU(
        user_id=current_user.id,
        sku=sku_data.sku,
        description=sku_data.description,
        is_active=sku_data.is_active
    )
    db.add(db_sku)
    db.commit()
    db.refresh(db_sku)
    return db_sku


@router.put("/excluded-skus/{sku_id}", response_model=ExcludedSKUResponse)
async def update_excluded_sku(
    sku_id: int,
    sku_data: ExcludedSKUUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an excluded SKU"""
    db_sku = db.query(ExcludedSKU).filter(
        ExcludedSKU.id == sku_id,
        ExcludedSKU.user_id == current_user.id
    ).first()

    if not db_sku:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Excluded SKU not found"
        )

    # Check for duplicate SKU if changing the SKU value
    if sku_data.sku and sku_data.sku != db_sku.sku:
        existing = db.query(ExcludedSKU).filter(
            ExcludedSKU.user_id == current_user.id,
            ExcludedSKU.sku == sku_data.sku,
            ExcludedSKU.id != sku_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SKU already exists in exclusion list"
            )

    for field, value in sku_data.dict(exclude_unset=True).items():
        setattr(db_sku, field, value)

    db.commit()
    db.refresh(db_sku)
    return db_sku


@router.delete("/excluded-skus/{sku_id}")
async def delete_excluded_sku(
    sku_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an excluded SKU"""
    db_sku = db.query(ExcludedSKU).filter(
        ExcludedSKU.id == sku_id,
        ExcludedSKU.user_id == current_user.id
    ).first()

    if not db_sku:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Excluded SKU not found"
        )

    db.delete(db_sku)
    db.commit()
    return {"message": "Excluded SKU deleted successfully"}


@router.get("/database-stats")
async def get_database_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get database statistics for the current user"""
    try:
        db_type = get_db_type()

        # Get basic stats
        stats = {
            "database_type": db_type,
            "stores": db.query(ShopifyStore).filter(ShopifyStore.user_id == current_user.id).count(),
            "rules": db.query(ProcessingRule).filter(ProcessingRule.user_id == current_user.id).count(),
            "order_logs": db.query(OrderLog).filter(OrderLog.user_id == current_user.id).count(),
            "fraud_analyses": db.query(FraudAnalysis).filter(FraudAnalysis.user_id == current_user.id).count(),
            "fraud_rules": db.query(FraudDetectionRule).filter(FraudDetectionRule.user_id == current_user.id).count(),
        }

        # Get additional stats for processed orders
        store_ids = db.query(ShopifyStore.id).filter(
            ShopifyStore.user_id == current_user.id
        ).all()
        store_ids = [s[0] for s in store_ids]

        if store_ids:
            stats["processed_orders"] = db.query(ProcessedOrder).filter(
                ProcessedOrder.store_id.in_(store_ids)
            ).count()
        else:
            stats["processed_orders"] = 0

        # Get database size if PostgreSQL
        if db_type == "postgresql":
            try:
                result = db.execute(text("SELECT pg_database_size(current_database())")).scalar()
                stats["database_size_bytes"] = result
                stats["database_size_mb"] = round(result / (1024 * 1024), 2)
            except Exception as e:
                logger.warning(f"Could not get database size: {str(e)}")
                stats["database_size_bytes"] = 0
                stats["database_size_mb"] = 0

        return stats

    except Exception as e:
        logger.error(f"Error getting database stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get database stats: {str(e)}"
        )


@router.post("/compact-database")
async def compact_database(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Run database maintenance operations"""
    try:
        db_type = get_db_type()

        if db_type == "postgresql":
            # PostgreSQL maintenance
            try:
                db.execute(text("VACUUM ANALYZE"))
                db.commit()
                return {
                    "message": "Database maintenance completed successfully",
                    "operation": "VACUUM ANALYZE"
                }
            except Exception as e:
                db.rollback()
                logger.error(f"Database maintenance failed: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Database maintenance failed: {str(e)}"
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported database type: {db_type}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during database maintenance: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run database maintenance: {str(e)}"
        )


# Fraud Sync Control Endpoints
@router.get("/fraud-sync-status")
async def get_fraud_sync_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current fraud sync status and statistics"""
    try:
        # Get recent fraud analyses count (last 7 days)
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


@router.post("/trigger-fraud-analysis")
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


@router.post("/reprocess-fraud-rules")
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
