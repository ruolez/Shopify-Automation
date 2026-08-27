from datetime import datetime, timezone

import pytest

from time_utils import local_day_bounds


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# Just past UTC midnight on Aug 27 is still the evening of Aug 26 in Chicago (CDT, UTC-5)
CHICAGO_EVENING = utc(2026, 8, 27, 0, 51)


@pytest.mark.parametrize(
    "now, tz_name, days_ago, expected",
    [
        (CHICAGO_EVENING, "America/Chicago", 0, (utc(2026, 8, 26, 5), utc(2026, 8, 27, 5))),
        (CHICAGO_EVENING, "America/Chicago", 1, (utc(2026, 8, 25, 5), utc(2026, 8, 26, 5))),
        (CHICAGO_EVENING, "UTC", 0, (utc(2026, 8, 27), utc(2026, 8, 28))),
        (CHICAGO_EVENING, None, 0, (utc(2026, 8, 27), utc(2026, 8, 28))),
        (CHICAGO_EVENING, "Not/AZone", 0, (utc(2026, 8, 27), utc(2026, 8, 28))),
        # US DST ends 2026-11-01: that Chicago day is 25 hours long
        (utc(2026, 11, 1, 12), "America/Chicago", 0, (utc(2026, 11, 1, 5), utc(2026, 11, 2, 6))),
        # US DST starts 2026-03-08: that Chicago day is 23 hours long
        (utc(2026, 3, 8, 12), "America/Chicago", 0, (utc(2026, 3, 8, 6), utc(2026, 3, 9, 5))),
    ],
)
def test_local_day_bounds_returns_utc_bounds_of_the_local_calendar_day(now, tz_name, days_ago, expected):
    assert local_day_bounds(now, tz_name, days_ago) == expected


def test_local_day_bounds_accepts_naive_utc_now():
    naive = CHICAGO_EVENING.replace(tzinfo=None)
    assert local_day_bounds(naive, "America/Chicago") == local_day_bounds(CHICAGO_EVENING, "America/Chicago")
