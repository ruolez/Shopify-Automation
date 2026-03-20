"""Shared dependencies for FastAPI routers"""
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from database import get_db
from models import User, Settings
from auth import get_current_user

logger = logging.getLogger(__name__)


def _format_timestamp_with_user_timezone(timestamp: datetime, user_id: int, db: Session) -> str:
    """Format timestamp using user's timezone settings"""
    if not timestamp:
        return None

    try:
        import pytz
        from datetime import timezone as tz

        # Get user's timezone settings
        user_settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        user_timezone = user_settings.timezone if user_settings and user_settings.timezone else "UTC"

        # Convert UTC timestamp to user's timezone
        user_tz = pytz.timezone(user_timezone)

        # Ensure timestamp is timezone-aware (assume UTC if naive)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=tz.utc)

        # Convert to user timezone and format
        user_time = timestamp.astimezone(user_tz)
        return user_time.isoformat()

    except Exception as e:
        logger.warning(f"Error formatting timestamp with user timezone: {str(e)}")
        # Fallback to UTC isoformat
        return timestamp.isoformat() if timestamp else None


__all__ = [
    'get_db',
    'get_current_user',
    '_format_timestamp_with_user_timezone',
    'logger',
]
