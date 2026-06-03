"""Trading calendar helpers for backtests."""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

import pandas as pd


def trading_days_between(start: date, end: date) -> List[date]:
    """Inclusive business days from start through end."""
    idx = pd.bdate_range(start=start, end=end, freq="C")
    return [d.date() for d in idx]


def extended_trading_calendar(
    first_day: date,
    last_day: date,
    *,
    hold_trading_days: int = 5,
) -> List[date]:
    """Calendar long enough to enter, hold, and exit after the last signal day."""
    buffer = max(hold_trading_days, 5) + 10
    end = last_day + timedelta(days=buffer)
    return trading_days_between(first_day, end)


def trading_day_on_or_before(d: date, calendar: Optional[List[date]] = None) -> date:
    cal = calendar or trading_days_between(d - timedelta(days=14), d)
    for day in reversed(cal):
        if day <= d:
            return day
    return d


def next_trading_day(d: date, calendar: List[date]) -> Optional[date]:
    for day in calendar:
        if day > d:
            return day
    return None


def add_trading_days(d: date, n: int, calendar: List[date]) -> Optional[date]:
    if n <= 0:
        return trading_day_on_or_before(d, calendar)
    anchor = trading_day_on_or_before(d, calendar)
    try:
        i = calendar.index(anchor)
    except ValueError:
        later = [x for x in calendar if x >= anchor]
        if not later:
            return None
        i = calendar.index(later[0])
    j = i + n
    if j >= len(calendar):
        return None
    return calendar[j]


def weekly_run_dates(end_date: date, weeks: int) -> List[date]:
    """
    One pipeline run per week, oldest first.
    Each date is the last US trading day on or before end_date - 7*k weeks.
    """
    cal = trading_days_between(end_date - timedelta(days=weeks * 7 + 21), end_date)
    runs: List[date] = []
    anchor = end_date
    for _ in range(weeks):
        run = trading_day_on_or_before(anchor, cal)
        if not runs or runs[-1] != run:
            runs.append(run)
        anchor = anchor - timedelta(days=7)
    return sorted(set(runs))
