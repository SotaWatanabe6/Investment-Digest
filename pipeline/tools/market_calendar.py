"""
NYSE market-day check. The digest is only useful to send on a day the
market was actually open — insider filings, news, and macro moves are all
thin to nonexistent on a weekend or holiday, so sending on those days would
mostly just be a "nothing to report" email nobody needs.

Holiday dates are hardcoded per year (verified against NYSE's official
published calendar, not derived from a formula) since observed dates shift
around weekends and don't follow a single consistent rule. This needs a new
entry added for each year the pipeline keeps running.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

# Source: NYSE Group's official 2025/2026/2027 holiday calendar announcement.
# Each is the actual observed closure date (e.g. Independence Day, July 4
# 2026, falls on a Saturday, so the market observes it on Friday July 3).
NYSE_HOLIDAYS: dict[int, set[str]] = {
    2026: {
        "2026-01-01",  # New Year's Day
        "2026-01-19",  # Martin Luther King, Jr. Day
        "2026-02-16",  # Washington's Birthday (Presidents Day)
        "2026-04-03",  # Good Friday
        "2026-05-25",  # Memorial Day
        "2026-06-19",  # Juneteenth National Independence Day
        "2026-07-03",  # Independence Day (observed; July 4 falls on a Saturday)
        "2026-09-07",  # Labor Day
        "2026-11-26",  # Thanksgiving Day
        "2026-12-25",  # Christmas Day
    },
}


def is_market_open(date_str: str | None = None) -> bool:
    """True if NYSE is open (regular trading day) on the given date
    (YYYY-MM-DD, defaults to today). False on weekends and holidays.

    If the year isn't in NYSE_HOLIDAYS (the table hasn't been updated for
    that year yet), this only checks the weekend and assumes it's a
    trading day otherwise -- fails open rather than silently skipping
    every day of a year nobody's added holiday data for yet.
    """
    if date_str is None:
        d = datetime.now(timezone.utc).date()
    else:
        d = date.fromisoformat(date_str)

    if d.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False

    holidays = NYSE_HOLIDAYS.get(d.year, set())
    return d.isoformat() not in holidays
