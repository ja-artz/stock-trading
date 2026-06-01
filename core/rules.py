"""Trading rules validation and defaults."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

DEFAULT_RULES: dict[str, Any] = {
    "max_position_pct_nav": 33,
    "max_new_positions_per_week": 5,
    "cash_floor_pct": 10,
    "max_open_option_positions": 2,
    "options_allowed": True,
    "shorts_allowed": True,
    "trade_commit_hours": 24,
    "weekly_plan_day": "Sunday",
    "weekly_plan_hour_local": 18,
    "timezone": "America/Los_Angeles",
}


@dataclass
class RuleViolation:
    code: str
    message: str
    severity: str = "error"  # error | warning


def parse_rules(rules_json: str | dict | None) -> dict[str, Any]:
    if rules_json is None:
        return dict(DEFAULT_RULES)
    if isinstance(rules_json, dict):
        base = dict(DEFAULT_RULES)
        base.update(rules_json)
        return base
    data = json.loads(rules_json)
    base = dict(DEFAULT_RULES)
    base.update(data)
    return base


def is_option_instrument(instrument_type: str) -> bool:
    t = (instrument_type or "stock").lower()
    return t in ("call_option", "put_option", "call", "put", "option")


def pacific_week_start(dt: datetime) -> datetime:
    tz = ZoneInfo("America/Los_Angeles")
    local = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    monday = local.date()
    while monday.weekday() != 0:
        from datetime import timedelta
        monday -= timedelta(days=1)
    return datetime.combine(monday, datetime.min.time(), tzinfo=tz)


def validate_trade(
    rules: dict[str, Any],
    *,
    cash_usd: float,
    nav_usd: float,
    positions: List[dict[str, Any]],
    side: str,
    ticker: str,
    instrument_type: str,
    quantity: float,
    price: float,
    new_positions_this_week: int,
    is_new_position: bool,
) -> List[RuleViolation]:
    violations: List[RuleViolation] = []
    side_l = side.lower()
    notional = abs(quantity) * price

    if is_option_instrument(instrument_type) and not rules.get("options_allowed", True):
        violations.append(RuleViolation("options_disabled", "Options are not allowed by trading rules."))

    open_options = sum(
        1 for p in positions
        if is_option_instrument(p.get("instrument_type", "stock")) and abs(p.get("quantity", 0)) > 0
    )
    adding_option = is_option_instrument(instrument_type) and side_l == "buy"
    if adding_option and open_options >= rules.get("max_open_option_positions", 2):
        existing = any(
            p.get("ticker", "").upper() == ticker.upper()
            and is_option_instrument(p.get("instrument_type", ""))
            for p in positions
        )
        if not existing:
            violations.append(
                RuleViolation(
                    "max_open_options",
                    f"At most {rules['max_open_option_positions']} open option positions allowed.",
                )
            )

    if is_new_position and side_l == "buy" and new_positions_this_week >= rules.get("max_new_positions_per_week", 5):
        violations.append(
            RuleViolation(
                "max_new_positions_week",
                f"Maximum {rules['max_new_positions_per_week']} new positions per week (Pacific).",
            )
        )

    if nav_usd > 0 and side_l == "buy":
        post_cash = cash_usd - notional
        floor_pct = rules.get("cash_floor_pct", 10)
        min_cash = nav_usd * floor_pct / 100.0
        if post_cash < min_cash:
            violations.append(
                RuleViolation(
                    "cash_floor",
                    f"Trade would leave cash below {floor_pct}% floor (${min_cash:.2f} required).",
                )
            )
        max_pos_pct = rules.get("max_position_pct_nav", 33)
        max_pos_value = nav_usd * max_pos_pct / 100.0
        current_pos = next((p for p in positions if p.get("ticker", "").upper() == ticker.upper()), None)
        current_val = 0.0
        if current_pos:
            current_val = abs(current_pos.get("quantity", 0)) * current_pos.get("mark_price", price)
        if current_val + notional > max_pos_value * 1.05:
            violations.append(
                RuleViolation(
                    "max_position_pct",
                    f"Position would exceed {max_pos_pct}% of NAV (~${max_pos_value:.2f}).",
                    severity="warning",
                )
            )

    if side_l == "sell" and quantity > 0:
        pos = next((p for p in positions if p.get("ticker", "").upper() == ticker.upper()), None)
        if pos and quantity > abs(pos.get("quantity", 0)) + 1e-9:
            violations.append(RuleViolation("insufficient_qty", "Sell quantity exceeds position."))

    return violations


def violations_to_messages(violations: List[RuleViolation]) -> List[str]:
    return [v.message for v in violations]


def has_blocking_violations(violations: List[RuleViolation]) -> bool:
    return any(v.severity == "error" for v in violations)
