"""Staleness helpers for trading plans (analysis freshness)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def format_pacific_display(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(ZoneInfo("America/Los_Angeles"))
        hour = local.strftime("%I").lstrip("0") or "12"
        return f"{local.strftime('%A, %b')} {local.day}, {hour}:{local.strftime('%M %p')} PT"
    except Exception:
        return iso_ts


def plan_staleness_fields(based_on_analysis_at: str) -> dict:
    try:
        based = datetime.fromisoformat(based_on_analysis_at.replace("Z", "+00:00"))
        if based.tzinfo is None:
            based = based.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_hours = (now - based).total_seconds() / 3600.0
    except Exception:
        age_hours = 0.0
    return {
        "based_on_analysis_at": based_on_analysis_at,
        "based_on_analysis_display": format_pacific_display(based_on_analysis_at),
        "staleness_banner": f"Based on analysis from {format_pacific_display(based_on_analysis_at)}",
        "is_stale": age_hours > 24,
        "age_hours": round(age_hours, 1),
    }
