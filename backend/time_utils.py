"""Calendar-day arithmetic in a user's configured timezone."""
from datetime import datetime, time, timedelta, timezone
from typing import Optional, Tuple

import pytz


def local_day_bounds(now: datetime, tz_name: Optional[str], days_ago: int = 0) -> Tuple[datetime, datetime]:
    """Return the UTC [start, end) of the calendar day that was `days_ago` days
    before `now` in `tz_name`. Unknown or empty timezones fall back to UTC."""
    try:
        tz = pytz.timezone(tz_name) if tz_name else pytz.utc
    except pytz.UnknownTimeZoneError:
        tz = pytz.utc

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    local_date = now.astimezone(tz).date() - timedelta(days=days_ago)
    start = tz.localize(datetime.combine(local_date, time.min))
    end = tz.localize(datetime.combine(local_date + timedelta(days=1), time.min))
    return start.astimezone(pytz.utc), end.astimezone(pytz.utc)
