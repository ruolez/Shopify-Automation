from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import os
import logging

from database import get_db
from models import AdminUser, AdminAuditLog

logger = logging.getLogger(__name__)

# Admin security configuration
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY")
if not ADMIN_SECRET_KEY:
    raise RuntimeError(
        "ADMIN_SECRET_KEY environment variable is not set. "
        "Please set a secure random key (at least 32 characters) in your .env file. "
        "You can generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )
ADMIN_ALGORITHM = "HS256"
ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES = 8 * 60  # 8 hours

admin_security = HTTPBearer()

def verify_admin_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash using bcrypt directly."""
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )

def get_admin_password_hash(password: str) -> str:
    """Hash a password using bcrypt directly."""
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

def create_admin_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "admin"})
    encoded_jwt = jwt.encode(to_encode, ADMIN_SECRET_KEY, algorithm=ADMIN_ALGORITHM)
    return encoded_jwt

def verify_admin_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, ADMIN_SECRET_KEY, algorithms=[ADMIN_ALGORITHM])
        username: str = payload.get("sub")
        token_type: str = payload.get("type")
        if username is None or token_type != "admin":
            return None
        return username
    except JWTError:
        return None

async def get_current_admin_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(admin_security),
    db: Session = Depends(get_db)
) -> AdminUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate admin credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        username = verify_admin_token(credentials.credentials)
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    admin_user = db.query(AdminUser).filter(
        AdminUser.username == username,
        AdminUser.is_active == True
    ).first()
    if admin_user is None:
        raise credentials_exception
    
    return admin_user

def log_admin_action(
    db: Session,
    admin_user: AdminUser,
    action: str,
    target_type: str = None,
    target_id: str = None,
    details: dict = None,
    ip_address: str = None,
    user_agent: str = None
):
    """Log admin actions for audit trail"""
    try:
        audit_log = AdminAuditLog(
            admin_user_id=admin_user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.add(audit_log)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log admin action: {e}")
        db.rollback()

def require_admin_role(required_roles: list = None):
    """Decorator to require specific admin roles"""
    if required_roles is None:
        required_roles = ["admin", "super_admin"]
    
    def role_dependency(admin_user: AdminUser = Depends(get_current_admin_user)):
        if admin_user.role not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return admin_user
    
    return role_dependency