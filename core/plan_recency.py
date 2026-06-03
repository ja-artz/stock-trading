"""Human-readable timing for on-demand trading plans (not fixed weekly cadence)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def parse_iso_ts(iso_ts: str) -> Optional[datetime]:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def minutes_since(iso_ts: str, *, now: Optional[datetime] = None) -> Optional[float]:
    dt = parse_iso_ts(iso_ts)
    if not dt:
        return None
    ref = now or datetime.now(timezone.utc)
    return max(0.0, (ref - dt).total_seconds() / 60.0)


def format_minutes_ago(minutes: float) -> str:
    if minutes < 1:
        return "just now"
    if minutes < 60:
        n = int(round(minutes))
        return f"{n} minute{'s' if n != 1 else ''} ago"
    if minutes < 24 * 60:
        h = minutes / 60.0
        if h < 2:
            return "about 1 hour ago"
        n = int(round(h))
        return f"{n} hour{'s' if n != 1 else ''} ago"
    days = minutes / (24 * 60)
    if days < 2:
        return "about 1 day ago"
    n = int(round(days))
    return f"{n} day{'s' if n != 1 else ''} ago"


def analysis_timestamps_match(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    da, db = parse_iso_ts(a), parse_iso_ts(b)
    if da and db:
        return abs((da - db).total_seconds()) < 2.0
    return a.strip() == b.strip()


def last_plan_timing_block(
    *,
    plan_at: Optional[str],
    based_on_analysis_at: Optional[str],
    current_analysis_at: str,
    current_analysis_run_id: int,
    last_analysis_run_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    mins = minutes_since(plan_at, now=now) if plan_at else None
    same_analysis = analysis_timestamps_match(based_on_analysis_at, current_analysis_at)
    if last_analysis_run_id is not None and current_analysis_run_id:
        same_run = int(last_analysis_run_id) == int(current_analysis_run_id)
    else:
        same_run = same_analysis

    return {
        "has_prior_plan": bool(plan_at),
        "plan_at": plan_at,
        "minutes_since_last_plan": round(mins, 1) if mins is not None else None,
        "last_plan_ago_label": format_minutes_ago(mins) if mins is not None else None,
        "last_plan_based_on_analysis_at": based_on_analysis_at,
        "current_analysis_at": current_analysis_at,
        "current_analysis_run_id": current_analysis_run_id,
        "analysis_unchanged_since_last_plan": same_analysis,
        "same_analysis_run_as_last_plan": same_run,
    }


def enrich_plan_context_row(plan_row: dict) -> dict:
    """Add recency fields to a plan dict for prompts/API."""
    plan_at = plan_row.get("plan_at")
    mins = minutes_since(plan_at) if plan_at else None
    payload = plan_row.get("payload") if isinstance(plan_row.get("payload"), dict) else {}
    if not payload and plan_row.get("payload_json"):
        import json

        try:
            payload = json.loads(plan_row["payload_json"])
        except Exception:
            payload = {}
    no_changes = bool(payload.get("no_changes") or payload.get("no_trade_week"))
    out = dict(plan_row)
    out["minutes_since_plan"] = round(mins, 1) if mins is not None else None
    out["plan_ago_label"] = format_minutes_ago(mins) if mins is not None else None
    out["no_changes"] = no_changes
    return out
