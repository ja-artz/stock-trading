"""Trading rules validation and defaults."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

from core.instruments import is_option_instrument_type, trade_notional

DEFAULT_RULES: dict[str, Any] = {
    "max_position_pct_nav": 33,
    "max_new_positions_per_week": 10,
    "cash_floor_pct": 10,
    "max_open_option_positions": 2,
    "options_allowed": True,
    "shorts_allowed": True,
    "trade_commit_hours": 24,
    "weekly_plan_day": "Sunday",
    "weekly_plan_hour_local": 18,
    "timezone": "America/Los_Angeles",
    "tier_1_pct": 15,
    "tier_2_pct": 55,
    "tier_3_pct": 25,
    "dry_powder_pct": 5,
    "tier_1_max_positions": 2,
    "tier_2_max_positions": 3,
    "tier_3_max_positions": 2,
    "tier_1_max_new_trades_per_month": 2,
    "max_sector_pct_nav": 40,
    "max_theme_pct_nav": 50,
    "max_portfolio_options_pct": 30,
    "tier_2_max_options_pct": 40,
    "tier_3_max_options_pct": 20,
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


def validate_rules_update(rules: dict[str, Any]) -> List[str]:
    """Return human-readable validation errors for a rules patch."""
    errors: List[str] = []

    tier_keys = ("tier_1_pct", "tier_2_pct", "tier_3_pct", "dry_powder_pct")
    if any(k in rules for k in tier_keys):
        merged = parse_rules(rules)
        tier_sum = sum(float(merged.get(k, 0)) for k in tier_keys)
        if abs(tier_sum - 100.0) > 0.01:
            errors.append(f"Tier budget percentages must sum to 100% (currently {tier_sum:.1f}%).")

    pct_fields = (
        "max_position_pct_nav",
        "cash_floor_pct",
        "max_sector_pct_nav",
        "max_theme_pct_nav",
        "max_portfolio_options_pct",
        "tier_2_max_options_pct",
        "tier_3_max_options_pct",
        *tier_keys,
    )
    for key in pct_fields:
        if key not in rules:
            continue
        try:
            val = float(rules[key])
        except (TypeError, ValueError):
            errors.append(f"{key} must be a number.")
            continue
        if val < 0 or val > 100:
            errors.append(f"{key} must be between 0 and 100.")

    int_fields = (
        "max_new_positions_per_week",
        "max_open_option_positions",
        "tier_1_max_positions",
        "tier_2_max_positions",
        "tier_3_max_positions",
        "tier_1_max_new_trades_per_month",
        "trade_commit_hours",
        "weekly_plan_hour_local",
    )
    for key in int_fields:
        if key not in rules:
            continue
        try:
            val = int(rules[key])
        except (TypeError, ValueError):
            errors.append(f"{key} must be an integer.")
            continue
        if val < 0:
            errors.append(f"{key} must be zero or greater.")

    if "weekly_plan_hour_local" in rules:
        hour = int(rules["weekly_plan_hour_local"])
        if hour < 0 or hour > 23:
            errors.append("weekly_plan_hour_local must be between 0 and 23.")

    return errors


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


def _tier_entry_violations(
    rules: dict[str, Any],
    *,
    portfolio_id: int,
    plan_item_id: Optional[int],
    ticker: str,
    instrument_type: str,
    notional: float,
    is_new_position: bool,
) -> List[RuleViolation]:
    from core.position_lots import count_tier1_opens_this_month, enrich_lots_with_marks, get_open_lots
    from core.tier_engine import ProposedEntry, build_tier_state, validate_proposed_entry
    from core.tier_config import normalize_capital_tier

    lots = enrich_lots_with_marks(portfolio_id, get_open_lots(portfolio_id))
    nav_state = None
    try:
        from core.portfolio import compute_nav

        nav_state = compute_nav(portfolio_id)
    except Exception:
        return []

    state = build_tier_state(
        nav_usd=nav_state["nav_usd"],
        cash_usd=nav_state["cash_usd"],
        lots=lots,
        rules=rules,
        tier_1_trades_this_month=count_tier1_opens_this_month(portfolio_id),
    )

    tier = 2
    sector = None
    theme = None
    corr = ticker.upper()
    conviction = None
    consensus = None
    if plan_item_id:
        from core.plan_execution import get_plan_item

        item = get_plan_item(plan_item_id)
        if item:
            tier = normalize_capital_tier(item.get("capital_tier")) or tier
            sector = item.get("sector")
            theme = item.get("theme_tag")
            corr = item.get("correlation_group") or ticker.upper()
            conviction = item.get("conviction_grade")
            consensus = item.get("persona_consensus")

    existing = any(
        l["ticker"].upper() == ticker.upper()
        and (l.get("instrument_type") or "stock") == instrument_type
        for l in lots
    )

    proposed = ProposedEntry(
        capital_tier=tier,
        ticker=ticker.upper(),
        instrument_type=instrument_type,
        notional_usd=notional,
        sector=sector,
        theme_tag=theme,
        correlation_group=corr,
        conviction_grade=conviction,
        persona_consensus=consensus,
        is_new_lot=is_new_position,
    )
    ok, viols = validate_proposed_entry(
        proposed, state, rules, existing_lot_for_ticker=existing
    )
    out: List[RuleViolation] = []
    for v in viols:
        out.append(RuleViolation(v["code"], v["message"], v.get("severity", "error")))
    return out


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
    portfolio_id: Optional[int] = None,
    plan_item_id: Optional[int] = None,
) -> List[RuleViolation]:
    violations: List[RuleViolation] = []
    side_l = side.lower()
    notional = trade_notional(quantity, price, instrument_type)

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
            current_val = float(current_pos.get("market_value") or 0)
            if current_val <= 0:
                current_val = trade_notional(
                    current_pos.get("quantity", 0),
                    current_pos.get("mark_price", price),
                    current_pos.get("instrument_type", "stock"),
                )
        if current_val + notional > max_pos_value * 1.05:
            violations.append(
                RuleViolation(
                    "max_position_pct",
                    f"Position would exceed {max_pos_pct}% of NAV (~${max_pos_value:.2f}).",
                    severity="error",
                )
            )

        if portfolio_id is not None:
            violations.extend(
                _tier_entry_violations(
                    rules,
                    portfolio_id=portfolio_id,
                    plan_item_id=plan_item_id,
                    ticker=ticker,
                    instrument_type=instrument_type,
                    notional=notional,
                    is_new_position=is_new_position,
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
