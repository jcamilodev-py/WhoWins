"""Calendar arithmetic in a user's own timezone.

Every deadline in WhoWins is local to the member it applies to, so "today" and
"midnight" are always questions about someone's timezone, never the server's.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo


def local_today(timezone: str) -> date:
    return datetime.now(ZoneInfo(timezone)).date()


def start_of_day(day: date, timezone: str) -> datetime:
    """The instant that day begins in that timezone, as an absolute point in time."""
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(timezone))
