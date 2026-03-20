"""Admin management endpoints"""
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db, engine, create_tables
from models import (
    User, ShopifyStore, ProcessingRule, OrderLog, ProcessedOrder,
    AdminUser, AdminAuditLog, TaskStatus
)
from admin_auth import (
    get_current_admin_user, create_admin_access_token,
    verify_admin_password, get_admin_password_hash,
    log_admin_action, require_admin_role
)
from auth import get_current_user
from schemas import (
    AdminUserCreate, AdminUserLogin, AdminUserChangePassword,
    AdminUserResponse, AdminTokenResponse, AdminAuditLogResponse,
    SystemStatsResponse, UserManagementResponse
)
from rate_limiting import limiter, ADMIN_LOGIN_LIMIT, PASSWORD_CHANGE_LIMIT
import database_utils

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/auth/login", response_model=AdminTokenResponse)
@limiter.limit(ADMIN_LOGIN_LIMIT)
async def admin_login(
    request: Request,
    admin_data: AdminUserLogin,
    db: Session = Depends(get_db)
):
    admin_user = db.query(AdminUser).filter(
        AdminUser.username == admin_data.username,
        AdminUser.is_active == True
    ).first()

    if not admin_user or not verify_admin_password(admin_data.password, admin_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )

    admin_user.last_login = datetime.now(timezone.utc)
    db.commit()

    log_admin_action(
        db=db,
        admin_user=admin_user,
        action="login",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    access_token = create_admin_access_token(data={"sub": admin_user.username})
    return AdminTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=8 * 60 * 60
    )


@router.get("/auth/me", response_model=AdminUserResponse)
async def get_current_admin_info(admin_user: AdminUser = Depends(get_current_admin_user)):
    return admin_user


@router.put("/auth/change-password")
@limiter.limit(PASSWORD_CHANGE_LIMIT)
async def admin_change_password(
    request: Request,
    password_data: AdminUserChangePassword,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    if not verify_admin_password(password_data.current_password, admin_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    admin_user.hashed_password = get_admin_password_hash(password_data.new_password)
    db.commit()

    log_admin_action(
        db=db,
        admin_user=admin_user,
        action="password_change",
        target_type="admin_user",
        target_id=str(admin_user.id)
    )

    return {"message": "Password changed successfully"}


@router.get("/stats", response_model=SystemStatsResponse)
async def get_system_stats(
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    stats = SystemStatsResponse(
        total_users=db.query(User).count(),
        active_users=db.query(User).filter(User.is_active == True).count(),
        total_stores=db.query(ShopifyStore).count(),
        active_stores=db.query(ShopifyStore).filter(ShopifyStore.is_active == True).count(),
        total_rules=db.query(ProcessingRule).count(),
        active_rules=db.query(ProcessingRule).filter(ProcessingRule.is_active == True).count(),
        total_processed_orders=db.query(ProcessedOrder).count(),
        total_order_logs=db.query(OrderLog).count(),
        recent_registrations=db.query(User).filter(User.created_at >= seven_days_ago).count()
    )

    return stats


@router.get("/users", response_model=List[UserManagementResponse])
async def get_all_users(
    skip: int = 0,
    limit: int = 100,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    from sqlalchemy import func

    stores_count_sub = (
        db.query(func.count(ShopifyStore.id))
        .filter(ShopifyStore.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    rules_count_sub = (
        db.query(func.count(ProcessingRule.id))
        .filter(ProcessingRule.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    last_activity_sub = (
        db.query(func.max(OrderLog.created_at))
        .filter(OrderLog.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )

    rows = (
        db.query(
            User,
            stores_count_sub.label("stores_count"),
            rules_count_sub.label("rules_count"),
            last_activity_sub.label("last_activity"),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [
        UserManagementResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            created_at=user.created_at,
            stores_count=stores_count or 0,
            rules_count=rules_count or 0,
            last_activity=last_activity,
        )
        for user, stores_count, rules_count, last_activity in rows
    ]


@router.put("/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: int,
    admin_user: AdminUser = Depends(require_admin_role(["admin", "super_admin"])),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_status = user.is_active
    user.is_active = not user.is_active
    db.commit()

    log_admin_action(
        db=db,
        admin_user=admin_user,
        action="user_status_change",
        target_type="user",
        target_id=str(user_id),
        details={"old_status": old_status, "new_status": user.is_active}
    )

    return {
        "message": f"User {'activated' if user.is_active else 'deactivated'} successfully",
        "is_active": user.is_active
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin_user: AdminUser = Depends(require_admin_role(["super_admin"])),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_email = user.email
    db.delete(user)
    db.commit()

    log_admin_action(
        db=db,
        admin_user=admin_user,
        action="user_delete",
        target_type="user",
        target_id=str(user_id),
        details={"deleted_user_email": user_email}
    )

    return {"message": "User deleted successfully"}


@router.get("/stores")
async def get_all_stores(
    skip: int = 0,
    limit: int = 100,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    stores = db.query(ShopifyStore).join(User).offset(skip).limit(limit).all()

    store_list = []
    for store in stores:
        store_list.append({
            "id": store.id,
            "shop_domain": store.shop_domain,
            "shop_name": store.shop_name,
            "is_active": store.is_active,
            "created_at": store.created_at,
            "last_sync": store.last_sync,
            "user": {
                "id": store.user.id,
                "email": store.user.email,
                "full_name": store.user.full_name
            }
        })

    return store_list


@router.get("/rules")
async def get_all_rules(
    skip: int = 0,
    limit: int = 100,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    rules = db.query(ProcessingRule).join(User).offset(skip).limit(limit).all()

    rule_list = []
    for rule in rules:
        rule_list.append({
            "id": rule.id,
            "name": rule.name,
            "description": rule.description,
            "is_active": rule.is_active,
            "priority": rule.priority,
            "created_at": rule.created_at,
            "user": {
                "id": rule.user.id,
                "email": rule.user.email,
                "full_name": rule.user.full_name
            }
        })

    return rule_list


@router.get("/audit-logs", response_model=List[AdminAuditLogResponse])
async def get_audit_logs(
    skip: int = 0,
    limit: int = 50,
    action: Optional[str] = None,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    query = db.query(AdminAuditLog).join(AdminUser)

    if action:
        query = query.filter(AdminAuditLog.action == action)

    logs = query.order_by(AdminAuditLog.created_at.desc()).offset(skip).limit(limit).all()
    return logs


@router.post("/users", response_model=AdminUserResponse)
async def create_admin_user(
    admin_data: AdminUserCreate,
    admin_user: AdminUser = Depends(require_admin_role(["super_admin"])),
    db: Session = Depends(get_db)
):
    existing_user = db.query(AdminUser).filter(
        (AdminUser.username == admin_data.username) | (AdminUser.email == admin_data.email)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists"
        )

    hashed_password = get_admin_password_hash(admin_data.password)
    new_admin = AdminUser(
        username=admin_data.username,
        email=admin_data.email,
        full_name=admin_data.full_name,
        hashed_password=hashed_password,
        role=admin_data.role
    )

    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)

    log_admin_action(
        db=db,
        admin_user=admin_user,
        action="admin_user_create",
        target_type="admin_user",
        target_id=str(new_admin.id),
        details={"username": admin_data.username, "role": admin_data.role}
    )

    return new_admin


@router.get("/order-logs")
async def get_all_order_logs(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    query = db.query(OrderLog).join(User).join(ShopifyStore)

    if status_filter:
        query = query.filter(OrderLog.status == status_filter)

    logs = query.order_by(OrderLog.created_at.desc()).offset(skip).limit(limit).all()

    log_list = []
    for log in logs:
        log_list.append({
            "id": log.id,
            "order_id": log.order_id,
            "order_number": log.order_number,
            "action": log.action,
            "status": log.status,
            "details": log.details,
            "error_message": log.error_message,
            "created_at": log.created_at,
            "user": {
                "id": log.user.id,
                "email": log.user.email,
                "full_name": log.user.full_name
            },
            "store": {
                "id": log.store.id,
                "shop_domain": log.store.shop_domain,
                "shop_name": log.store.shop_name
            }
        })

    return log_list


@router.get("/database/backup")
async def backup_database(
    request: Request,
    admin_user: AdminUser = Depends(require_admin_role(["super_admin"])),
    db: Session = Depends(get_db)
):
    """Download a backup of the database"""
    try:
        from db_utils import get_db_type

        db_type = get_db_type()
        db_url = os.getenv("DATABASE_URL")

        if not db_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="DATABASE_URL environment variable is not set"
            )

        if db_type == "postgresql":
            match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', db_url)
            if not match:
                raise ValueError("Invalid PostgreSQL connection string")

            pg_user, pg_pass, pg_host, pg_port, pg_db = match.groups()

            with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False) as tmp_file:
                backup_path = tmp_file.name

            env = os.environ.copy()
            env['PGPASSWORD'] = pg_pass

            cmd = [
                "pg_dump",
                "-h", pg_host,
                "-p", pg_port,
                "-U", pg_user,
                "-d", pg_db,
                "--clean", "--if-exists", "--no-owner", "--no-privileges"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if result.returncode != 0:
                raise Exception(f"pg_dump failed: {result.stderr}")

            with open(backup_path, 'w') as f:
                f.write(result.stdout)

            db_info = database_utils.get_database_info_postgres(db)

            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            filename = f"shopify_automation_backup_{timestamp}_postgres.sql"

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported database type: {db_type}"
            )

        log_admin_action(
            db=db,
            admin_user=admin_user,
            action="database_backup",
            details={
                "database_type": db_type,
                "file_size_mb": db_info.get("size_mb", 0),
                "user_count": db_info.get("user_count", 0),
                "store_count": db_info.get("store_count", 0)
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")
        )

        media_type = "application/sql"
        response = FileResponse(
            path=backup_path,
            filename=filename,
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

        if db_type == "postgresql":
            from starlette.background import BackgroundTask
            response.background = BackgroundTask(os.unlink, backup_path)

        return response

    except Exception as e:
        logger.error(f"Database backup failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backup failed: {str(e)}"
        )


@router.post("/database/restore")
async def restore_database(
    file: UploadFile = File(...),
    request: Request = None,
    admin_user: AdminUser = Depends(require_admin_role(["super_admin"])),
    db: Session = Depends(get_db)
):
    """Restore database from uploaded file"""
    temp_file_path = None
    try:
        from db_utils import get_db_type

        db_type = get_db_type()
        db_url = os.getenv("DATABASE_URL")

        if not db_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="DATABASE_URL environment variable is not set"
            )

        if db_type == "postgresql":
            if not (file.filename.endswith('.sql') or file.filename.endswith('.dump')):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid file type for PostgreSQL. Only .sql or .dump files are allowed"
                )

            with tempfile.NamedTemporaryFile(delete=False, suffix='.sql') as temp_file:
                temp_file_path = temp_file.name
                content = await file.read()
                temp_file.write(content)

            match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', db_url)
            if not match:
                raise ValueError("Invalid PostgreSQL connection string")

            pg_user, pg_pass, pg_host, pg_port, pg_db = match.groups()

            current_info = database_utils.get_database_info_postgres(db)

            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            backup_file = f"/tmp/pre_restore_backup_{timestamp}.sql"

            env = os.environ.copy()
            env['PGPASSWORD'] = pg_pass

            backup_cmd = [
                "pg_dump",
                "-h", pg_host,
                "-p", pg_port,
                "-U", pg_user,
                "-d", pg_db,
                "--clean", "--if-exists", "--no-owner", "--no-privileges",
                "-f", backup_file
            ]
            subprocess.run(backup_cmd, check=True, env=env)
            logger.info(f"Created pre-restore backup: {backup_file}")

            db.close()
            engine.dispose()

            restore_cmd = [
                "psql",
                "-h", pg_host,
                "-p", pg_port,
                "-U", pg_user,
                "-d", pg_db,
                "-f", temp_file_path
            ]

            result = subprocess.run(restore_cmd, capture_output=True, text=True, env=env)
            if result.returncode != 0:
                logger.error(f"PostgreSQL restore error: {result.stderr}")
                rollback_cmd = [
                    "psql",
                    "-h", pg_host,
                    "-p", pg_port,
                    "-U", pg_user,
                    "-d", pg_db,
                    "-f", backup_file
                ]
                subprocess.run(rollback_cmd, check=True, env=env)
                raise Exception(f"Restore failed: {result.stderr}")

            create_tables()
            new_db = next(get_db())
            upload_info = database_utils.get_database_info_postgres(new_db)

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported database type: {db_type}"
            )

        try:
            log_admin_action(
                db=new_db,
                admin_user=admin_user,
                action="database_restore",
                details={
                    "database_type": db_type,
                    "uploaded_file": file.filename,
                    "uploaded_size_mb": upload_info.get("size_mb", 0),
                    "uploaded_user_count": upload_info.get("user_count", 0),
                    "uploaded_store_count": upload_info.get("store_count", 0),
                    "previous_size_mb": current_info.get("size_mb", 0),
                    "previous_user_count": current_info.get("user_count", 0),
                    "previous_store_count": current_info.get("store_count", 0)
                },
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent") if request else None
            )
        finally:
            new_db.close()

        return {
            "message": "Database restored successfully",
            "database_type": db_type,
            "details": {
                "users_restored": upload_info.get("user_count", 0),
                "stores_restored": upload_info.get("store_count", 0),
                "rules_restored": upload_info.get("rule_count", 0)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database restore failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Restore failed: {str(e)}"
        )
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)


@router.get("/database/info")
async def get_database_info(
    admin_user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Get information about the current database"""
    try:
        from db_utils import get_db_type
        db_type = get_db_type()
        db_url = os.getenv("DATABASE_URL")

        if not db_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="DATABASE_URL environment variable is not set"
            )

        if db_type == "postgresql":
            info = database_utils.get_database_info_postgres(db)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported database type: {db_type}"
            )

        info["database_type"] = db_type

        last_backup = db.query(AdminAuditLog).filter(
            AdminAuditLog.action == "database_backup"
        ).order_by(AdminAuditLog.created_at.desc()).first()

        if last_backup:
            info["last_backup"] = {
                "timestamp": last_backup.created_at.isoformat(),
                "by": last_backup.admin_user.username
            }
        else:
            info["last_backup"] = None

        return info
    except Exception as e:
        logger.error(f"Failed to get database info: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get database info: {str(e)}"
        )


@router.delete("/clear-error-logs")
async def clear_error_logs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Clear only error logs and failed tasks for the current user - preserves successful order logs"""
    try:
        error_logs_count = db.query(OrderLog).filter(
            OrderLog.user_id == current_user.id,
            OrderLog.status == "error"
        ).count()

        failed_tasks_count = db.query(TaskStatus).filter(
            TaskStatus.user_id == current_user.id,
            TaskStatus.status == "failed"
        ).count()

        db.query(OrderLog).filter(
            OrderLog.user_id == current_user.id,
            OrderLog.status == "error"
        ).delete()

        db.query(TaskStatus).filter(
            TaskStatus.user_id == current_user.id,
            TaskStatus.status == "failed"
        ).delete()

        db.commit()

        return {
            "message": f"Successfully cleared {error_logs_count} error logs and {failed_tasks_count} failed tasks",
            "deleted_error_logs": error_logs_count,
            "deleted_failed_tasks": failed_tasks_count
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error clearing error logs and failed tasks: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear error logs and failed tasks"
        )
