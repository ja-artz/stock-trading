"""Scan scheduler — configurable scan times and entry cutoff."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import List, Optional
from zoneinfo import ZoneInfo

from intraday_momentum.settings import StrategyConfig


@dataclass
class ScanWindow:
    index: int
    scan_time: datetime


@dataclass
class ScanPlan:
    session_date: date
    windows: List[ScanWindow] = field(default_factory=list)
    entry_cutoff: datetime = field(default_factory=datetime.now)
    max_positions: int = 3


def _parse_time(t: str) -> time:
    hour, minute = t.split(":")
    return time(int(hour), int(minute))


def build_scan_plan(session_date: date, strategy: StrategyConfig) -> ScanPlan:
    execution = strategy.execution
    tz = ZoneInfo(execution.get("timezone", "America/Los_Angeles"))
    scan_times = execution.get("scan_times", ["06:35", "06:50"])
    cutoff_str = execution.get("entry_cutoff", "07:30")
    max_positions = int(execution.get("max_positions", 3))

    windows: List[ScanWindow] = []
    for i, scan_str in enumerate(scan_times):
        t = _parse_time(scan_str)
        scan_dt = datetime.combine(session_date, t, tzinfo=tz)
        windows.append(ScanWindow(index=i, scan_time=scan_dt))

    cutoff_t = _parse_time(cutoff_str)
    entry_cutoff = datetime.combine(session_date, cutoff_t, tzinfo=tz)

    return ScanPlan(
        session_date=session_date,
        windows=windows,
        entry_cutoff=entry_cutoff,
        max_positions=max_positions,
    )


def active_scan_windows(
    plan: ScanPlan,
    positions_taken: int,
) -> List[ScanWindow]:
    if positions_taken >= plan.max_positions:
        return []
    return [w for w in plan.windows if w.scan_time <= plan.entry_cutoff]


def _plan_now(plan: ScanPlan, now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(tz=plan.entry_cutoff.tzinfo)
    if now.tzinfo is None:
        return now.replace(tzinfo=plan.entry_cutoff.tzinfo)
    return now.astimezone(plan.entry_cutoff.tzinfo)


def live_scan_allowed(plan: ScanPlan, now: Optional[datetime] = None) -> bool:
    """Live scan may run anytime before the configured entry cutoff."""
    return _plan_now(plan, now) <= plan.entry_cutoff
