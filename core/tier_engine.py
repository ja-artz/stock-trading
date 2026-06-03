"""Deterministic capital tier state, exit evaluation, entry validation, and triage."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from core.plan_consensus import consensus_agree_count
from core.rules import is_option_instrument
from core.tier_config import (
    B_PLUS_TIER_ONLY,
    CONVICTION_DEPLOY,
    DEPLOYABLE_TIERS,
    DRY_POWDER_TIER,
    PROFIT_RECYCLING,
    THESIS_EXIT_ACTIONS,
    TIER_CATALYST_WEEKS,
    TIER_EXPECTED_HORIZON,
    TIER_HOLD_DAYS_MAX,
    TIER_LOSS_LADDERS,
    TIER_PROFIT_LADDERS,
    TIER_TIME_RULES,
    ExitStep,
    LEAPS_MIN_MONTHS,
    normalize_capital_tier,
    normalize_conviction,
    tier_budget_pct,
    tier_max_positions,
)


@dataclass
class TierBucket:
    tier: int
    budget_pct: float
    budget_usd: float
    deployed_usd: float
    available_usd: float
    position_count: int
    max_positions: int
    options_usd: float
    options_pct_of_tier: float


@dataclass
class TierState:
    nav_usd: float
    cash_usd: float
    dry_powder_usd: float
    deployable_cash_usd: float
    buckets: Dict[int, TierBucket] = field(default_factory=dict)
    total_options_usd: float = 0.0
    total_options_pct_nav: float = 0.0
    sector_exposure: Dict[str, float] = field(default_factory=dict)
    theme_exposure: Dict[str, float] = field(default_factory=dict)
    correlation_groups: Dict[str, float] = field(default_factory=dict)
    tier_1_trades_this_month: int = 0
    over_capacity_tiers: List[int] = field(default_factory=list)


@dataclass
class ActionItemDraft:
    position_lot_id: Optional[int]
    plan_item_id: Optional[int]
    ticker: str
    priority: str
    action: str
    reason_code: str
    detail: Dict[str, Any]


@dataclass
class ProposedEntry:
    capital_tier: int
    ticker: str
    instrument_type: str
    notional_usd: float
    sector: Optional[str] = None
    theme_tag: Optional[str] = None
    correlation_group: Optional[str] = None
    conviction_grade: Optional[str] = None
    persona_consensus: Optional[dict] = None
    is_new_lot: bool = True
    expiry: Optional[str] = None


@dataclass
class TriageResult:
    suggested_tier: Optional[int]
    deploy_fraction: float
    pass_trade: bool
    reasons: List[str]


def _parse_date(val: Any) -> Optional[date]:
    if not val:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    s = str(val).strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def days_held(entry_date: date, as_of: date) -> int:
    return max(0, (as_of - entry_date).days)


def pl_pct(entry_price: float, mark_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return (mark_price / entry_price - 1.0) * 100.0


def days_to_expiry(expiry: Any, as_of: date) -> Optional[int]:
    exp = _parse_date(expiry)
    if not exp:
        return None
    return (exp - as_of).days


def _partial_exits_fired(lot: dict) -> set[str]:
    raw = lot.get("partial_exits_json") or "[]"
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    if not isinstance(raw, list):
        return set()
    return {str(x) for x in raw}


def _ladder_fired(ladder: List[ExitStep], pl: float, fired: set[str]) -> Optional[ExitStep]:
    for step in ladder:
        if step.reason_code in fired:
            continue
        if step.threshold_pct >= 0 and pl >= step.threshold_pct:
            return step
        if step.threshold_pct < 0 and pl <= step.threshold_pct:
            return step
    return None


def build_tier_state(
    *,
    nav_usd: float,
    cash_usd: float,
    lots: List[dict],
    rules: dict[str, Any],
    tier_1_trades_this_month: int = 0,
) -> TierState:
    dry_pct = tier_budget_pct(rules, DRY_POWDER_TIER)
    dry_usd = nav_usd * dry_pct / 100.0
    cash_floor_pct = float(rules.get("cash_floor_pct", 10))
    reserved = max(dry_usd, nav_usd * cash_floor_pct / 100.0)
    deployable_cash = max(0.0, cash_usd - reserved)

    buckets: Dict[int, TierBucket] = {}
    sector_exp: Dict[str, float] = {}
    theme_exp: Dict[str, float] = {}
    corr_exp: Dict[str, float] = {}
    total_options = 0.0

    for tier in list(DEPLOYABLE_TIERS) + [DRY_POWDER_TIER]:
        pct = tier_budget_pct(rules, tier)
        budget = nav_usd * pct / 100.0
        buckets[tier] = TierBucket(
            tier=tier,
            budget_pct=pct,
            budget_usd=budget,
            deployed_usd=0.0,
            available_usd=budget,
            position_count=0,
            max_positions=tier_max_positions(rules, tier),
            options_usd=0.0,
            options_pct_of_tier=0.0,
        )

    for lot in lots:
        tier = normalize_capital_tier(lot.get("capital_tier")) or 2
        mv = float(lot.get("market_value") or 0)
        if tier not in buckets:
            continue
        b = buckets[tier]
        b.deployed_usd += mv
        b.position_count += 1
        if is_option_instrument(lot.get("instrument_type", "stock")):
            b.options_usd += mv
            total_options += mv
        sec = (lot.get("sector") or "").strip().lower()
        if sec:
            sector_exp[sec] = sector_exp.get(sec, 0.0) + mv
        theme = (lot.get("theme_tag") or "").strip().lower()
        if theme:
            theme_exp[theme] = theme_exp.get(theme, 0.0) + mv
        cg = (lot.get("correlation_group") or lot.get("ticker") or "").strip().upper()
        if cg:
            corr_exp[cg] = corr_exp.get(cg, 0.0) + mv

    over: List[int] = []
    for tier, b in buckets.items():
        if tier == DRY_POWDER_TIER:
            continue
        b.available_usd = max(0.0, b.budget_usd - b.deployed_usd)
        if b.deployed_usd > 0:
            b.options_pct_of_tier = (b.options_usd / b.deployed_usd) * 100.0
        if b.position_count > b.max_positions:
            over.append(tier)

    return TierState(
        nav_usd=nav_usd,
        cash_usd=cash_usd,
        dry_powder_usd=dry_usd,
        deployable_cash_usd=deployable_cash,
        buckets=buckets,
        total_options_usd=total_options,
        total_options_pct_nav=(total_options / nav_usd * 100.0) if nav_usd > 0 else 0.0,
        sector_exposure=sector_exp,
        theme_exposure=theme_exp,
        correlation_groups=corr_exp,
        tier_1_trades_this_month=tier_1_trades_this_month,
        over_capacity_tiers=over,
    )


def evaluate_position_exits(
    lot: dict,
    *,
    mark_price: float,
    as_of: date,
) -> List[ActionItemDraft]:
    """Evaluate mandatory exits, profit/loss ladders, and thesis status for one open lot."""
    items: List[ActionItemDraft] = []
    tier = normalize_capital_tier(lot.get("capital_tier")) or 2
    ticker = (lot.get("ticker") or "").upper()
    entry = _parse_date(lot.get("entry_date"))
    if not entry:
        return items

    entry_price = float(lot.get("entry_price") or 0)
    pl = pl_pct(entry_price, mark_price)
    held = days_held(entry, as_of)
    fired = _partial_exits_fired(lot)
    lot_id = lot.get("id")
    plan_id = lot.get("plan_item_id")

    def draft(action: str, reason: str, priority: str, **detail: Any) -> None:
        items.append(
            ActionItemDraft(
                position_lot_id=lot_id,
                plan_item_id=plan_id,
                ticker=ticker,
                priority=priority,
                action=action,
                reason_code=reason,
                detail={
                    "pl_pct": round(pl, 2),
                    "days_held": held,
                    "capital_tier": tier,
                    **detail,
                },
            )
        )

    # Thesis-driven (after mandatory time in discipline runner order — here we collect all)
    thesis = (lot.get("thesis_status") or "active").strip().lower()
    if thesis in THESIS_EXIT_ACTIONS:
        act, reason, pri = THESIS_EXIT_ACTIONS[thesis]
        if reason not in fired:
            draft(act, reason, pri, thesis_status=thesis)

    time_rules = TIER_TIME_RULES.get(tier, {})
    max_days = time_rules.get("max_hold_days") or TIER_HOLD_DAYS_MAX.get(tier)
    if max_days and held >= max_days:
        draft(
            "force_exit",
            time_rules.get("force_exit_reason") or time_rules.get("force_decision_reason") or f"tier_{tier}_max_hold",
            "critical",
            max_hold_days=max_days,
        )

    if is_option_instrument(lot.get("instrument_type", "stock")):
        dte = days_to_expiry(lot.get("expiry"), as_of)
        warn = time_rules.get("option_expiry_warn_days")
        if warn is not None and dte is not None and dte <= warn:
            draft("decide_roll_or_close", "options_expiry_approaching", "high", days_to_expiry=dte)

    if tier == 2 and held >= time_rules.get("reduce_at_days", 90):
        if "tier_2_no_progress_3mo" not in fired and thesis == "stalled":
            draft("partial_50_reduce", "tier_2_no_progress_3mo", "high")

    if tier == 3 and held >= time_rules.get("defeat_at_days", 183):
        if pl <= time_rules.get("defeat_down_pct", -30) and "tier_3_down_30_at_6mo" not in fired:
            draft("close_all", "tier_3_down_30_at_6mo", "critical")

    # Loss before profit (stricter first)
    loss_step = _ladder_fired(TIER_LOSS_LADDERS.get(tier, []), pl, fired)
    if loss_step:
        draft(loss_step.action, loss_step.reason_code, loss_step.priority)

    profit_step = _ladder_fired(TIER_PROFIT_LADDERS.get(tier, []), pl, fired)
    if profit_step:
        draft(profit_step.action, profit_step.reason_code, profit_step.priority)
        recycling = PROFIT_RECYCLING.get(tier)
        if recycling:
            items[-1].detail["profit_recycling"] = [
                {"dest_tier": t, "fraction": f} for t, f in recycling
            ]

    if tier == 2 and time_rules.get("review_interval_days"):
        if held > 0 and held % time_rules["review_interval_days"] < 2:
            draft("monthly_review", "tier_2_monthly_review", "medium")

    if tier == 3 and time_rules.get("review_interval_days"):
        if held > 0 and held % time_rules["review_interval_days"] < 2:
            draft("quarterly_review", "tier_3_quarterly_review", "medium")

    return items


def validate_proposed_entry(
    proposed: ProposedEntry,
    state: TierState,
    rules: dict[str, Any],
    *,
    existing_lot_for_ticker: bool = False,
) -> Tuple[bool, List[dict[str, str]]]:
    violations: List[dict[str, str]] = []

    def err(code: str, message: str) -> None:
        violations.append({"code": code, "message": message, "severity": "error"})

    def warn(code: str, message: str) -> None:
        violations.append({"code": code, "message": message, "severity": "warning"})

    tier = proposed.capital_tier
    if tier == DRY_POWDER_TIER:
        err("tier_4_no_deploy", "Tier 4 is dry powder — cannot open new positions.")
        return False, violations

    if tier not in DEPLOYABLE_TIERS:
        err("invalid_tier", f"Invalid capital_tier: {tier}")
        return False, violations

    bucket = state.buckets.get(tier)
    if not bucket:
        err("invalid_tier", f"No bucket for tier {tier}")
        return False, violations

    if state.over_capacity_tiers and tier in state.over_capacity_tiers:
        warn("tier_capacity_review", f"Tier {tier} exceeds max positions — review before adding.")

    if proposed.is_new_lot and not existing_lot_for_ticker:
        if bucket.position_count >= bucket.max_positions:
            err("tier_max_positions", f"Tier {tier} already has {bucket.position_count} positions (max {bucket.max_positions}).")
        if tier == 1:
            max_mo = int(rules.get("tier_1_max_new_trades_per_month", 2))
            if state.tier_1_trades_this_month >= max_mo:
                err("tier_1_monthly_trades", f"Tier 1 max {max_mo} new trades per month reached.")

    if proposed.notional_usd > bucket.available_usd + 1.0:
        err(
            "tier_budget_exceeded",
            f"Tier {tier} available ${bucket.available_usd:.2f}; proposed ${proposed.notional_usd:.2f}.",
        )

    if proposed.notional_usd > state.deployable_cash_usd + 1.0:
        err(
            "deployable_cash",
            f"Deployable cash ${state.deployable_cash_usd:.2f} insufficient for ${proposed.notional_usd:.2f}.",
        )

    max_pos_pct = float(rules.get("max_position_pct_nav", 33))
    max_pos = state.nav_usd * max_pos_pct / 100.0
    ticker_key = proposed.ticker.upper()
    cg = (proposed.correlation_group or ticker_key).upper()
    existing_corr = state.correlation_groups.get(cg, 0.0)
    if existing_corr + proposed.notional_usd > max_pos * 1.01:
        err(
            "correlation_group_cap",
            f"Correlation group {cg} would exceed {max_pos_pct}% NAV (~${max_pos:.2f}).",
        )
    elif proposed.notional_usd > max_pos * 1.01:
        err("max_position_pct", f"Position would exceed {max_pos_pct}% of NAV.")

    sector = (proposed.sector or "").strip().lower()
    if sector:
        max_sec = float(rules.get("max_sector_pct_nav", 40))
        sec_val = state.sector_exposure.get(sector, 0.0) + proposed.notional_usd
        if state.nav_usd > 0 and sec_val / state.nav_usd * 100 > max_sec + 0.5:
            err("max_sector_pct", f"Sector {sector} would exceed {max_sec}% of NAV.")

    theme = (proposed.theme_tag or "").strip().lower()
    if theme:
        max_theme = float(rules.get("max_theme_pct_nav", 50))
        th_val = state.theme_exposure.get(theme, 0.0) + proposed.notional_usd
        if state.nav_usd > 0 and th_val / state.nav_usd * 100 > max_theme + 0.5:
            err("max_theme_pct", f"Theme {theme} would exceed {max_theme}% of NAV.")

    is_opt = is_option_instrument(proposed.instrument_type)
    max_port_opt = float(rules.get("max_portfolio_options_pct", 30))
    post_opt = state.total_options_usd + (proposed.notional_usd if is_opt else 0)
    if state.nav_usd > 0 and post_opt / state.nav_usd * 100 > max_port_opt + 0.5:
        err("max_portfolio_options_pct", f"Portfolio options would exceed {max_port_opt}% of NAV.")

    if is_opt:
        tier_opt_cap = float(rules.get(f"tier_{tier}_max_options_pct", rules.get("tier_2_max_options_pct", 40)))
        post_tier_opt = bucket.options_usd + proposed.notional_usd
        post_deploy = bucket.deployed_usd + proposed.notional_usd
        if post_deploy > 0 and post_tier_opt / post_deploy * 100 > tier_opt_cap + 0.5:
            err("tier_options_pct", f"Tier {tier} options would exceed {tier_opt_cap}% of tier deployment.")

    grade = normalize_conviction(proposed.conviction_grade)
    consensus_n = consensus_agree_count(proposed.persona_consensus)
    if grade == "B":
        err("conviction_pass", "Conviction B — pass on new entry.")
    elif grade == "B_plus" and tier != B_PLUS_TIER_ONLY:
        err("conviction_b_plus_tier1", "B+ conviction only allowed on Tier 1.")
    elif grade and grade in CONVICTION_DEPLOY:
        frac = CONVICTION_DEPLOY[grade].get(min(consensus_n, 3), 0.0)
        if frac <= 0:
            err("conviction_insufficient", f"{grade} with {consensus_n}/3 consensus — insufficient to deploy.")

    blocking = [v for v in violations if v["severity"] == "error"]
    return len(blocking) == 0, violations


def triage_story_to_tier(
    *,
    catalyst_weeks: float,
    conviction_grade: Optional[str],
    consensus_count: int,
    tier_state: TierState,
    rules: dict[str, Any],
) -> TriageResult:
    reasons: List[str] = []
    grade = normalize_conviction(conviction_grade) or "B"

    if grade == "B":
        return TriageResult(None, 0.0, True, ["Conviction B — pass entirely."])

    suggested: Optional[int] = None
    for tier in DEPLOYABLE_TIERS:
        lo, hi = TIER_CATALYST_WEEKS[tier]
        if lo <= catalyst_weeks <= hi:
            suggested = tier
            break
    if suggested is None:
        if catalyst_weeks <= TIER_CATALYST_WEEKS[1][1]:
            suggested = 1
        elif catalyst_weeks <= TIER_CATALYST_WEEKS[2][1]:
            suggested = 2
        else:
            suggested = 3
        reasons.append(f"Catalyst {catalyst_weeks:.0f}w mapped to tier {suggested}.")

    if grade == "B_plus" and consensus_count >= 2:
        suggested = B_PLUS_TIER_ONLY
        reasons.append("B+ with 2/3 → Tier 1 quick strike only.")

    deploy_frac = CONVICTION_DEPLOY.get(grade, {}).get(min(consensus_count, 3), 0.0)
    if deploy_frac <= 0:
        return TriageResult(suggested, 0.0, True, reasons + ["Insufficient conviction/consensus to deploy."])

    bucket = tier_state.buckets.get(suggested or 1)
    if bucket and bucket.available_usd <= 0 and bucket.position_count >= bucket.max_positions:
        for alt in DEPLOYABLE_TIERS:
            if alt == suggested:
                continue
            b = tier_state.buckets.get(alt)
            if b and b.available_usd > 0 and b.position_count < b.max_positions:
                reasons.append(f"Tier {suggested} full — consider tier {alt}.")
                suggested = alt
                break
        else:
            reasons.append("All tiers full — pass (miss-it rule).")
            return TriageResult(suggested, 0.0, True, reasons)

    return TriageResult(suggested, deploy_frac, False, reasons)


def check_tier_horizon_coherence(
    capital_tier: Optional[int],
    horizon: Optional[str],
    expected_exit_months: Optional[float] = None,
) -> List[str]:
    warnings: List[str] = []
    tier = normalize_capital_tier(capital_tier)
    if not tier or tier == DRY_POWDER_TIER:
        return warnings
    expected = TIER_EXPECTED_HORIZON.get(tier)
    h = (horizon or "").strip().lower()
    if expected and h and h != expected:
        warnings.append(
            f"capital_tier {tier} typically pairs with horizon '{expected}', got '{h}'"
        )
    if expected_exit_months is not None and tier in TIER_CATALYST_WEEKS:
        em_weeks = float(expected_exit_months) * 4.33
        lo, hi = TIER_CATALYST_WEEKS[tier]
        if em_weeks < lo * 0.75 or em_weeks > hi * 1.25:
            warnings.append(
                f"expected_exit_months ({expected_exit_months}) outside tier {tier} catalyst window "
                f"({lo:.0f}–{hi:.0f} weeks)"
            )
    return warnings


def forced_exit_date_for_tier(tier: int, entry_date: date) -> Optional[str]:
    max_days = TIER_HOLD_DAYS_MAX.get(tier)
    if not max_days:
        return None
    return (entry_date + timedelta(days=max_days)).isoformat()
