"""Capital tier budgets, exit ladders, and conviction deploy multipliers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Deployable capital tiers (4 = dry powder, not deployable)
DEPLOYABLE_TIERS = (1, 2, 3)
DRY_POWDER_TIER = 4

# Human-readable tier identity (capital_tier 1–4 stays numeric in DB/code)
TIER_SLUGS: Dict[int, str] = {
    1: "quick_strike",
    2: "core_opportunity",
    3: "long_conviction",
    4: "dry_powder",
}

TIER_NAMES: Dict[int, str] = {
    1: "Quick Strike",
    2: "Core Opportunity",
    3: "Long Conviction",
    4: "Dry Powder",
}

TIER_HINTS: Dict[int, str] = {
    1: "1–4 week catalysts · short horizon · max 28-day hold",
    2: "3–6 month thesis · medium horizon · core book",
    3: "6–12 month themes · long horizon · patient capital",
    4: "Cash reserve only · not for new positions",
}

TIER_BUDGET_PCT_DEFAULTS: Dict[int, float] = {
    1: 15.0,
    2: 55.0,
    3: 25.0,
    4: 5.0,
}

TIER_MAX_POSITIONS_DEFAULTS: Dict[int, int] = {
    1: 2,
    2: 3,
    3: 2,
    4: 0,
}

TIER_EXPECTED_HORIZON: Dict[int, str] = {
    1: "short",
    2: "medium",
    3: "long",
}

# Catalyst window for triage (weeks)
TIER_CATALYST_WEEKS: Dict[int, Tuple[float, float]] = {
    1: (1.0, 4.0),
    2: (12.0, 26.0),
    3: (26.0, 52.0),
}

TIER_HOLD_DAYS_MAX: Dict[int, Optional[int]] = {
    1: 28,
    2: 183,
    3: 365,
}

TIER_OPTIONS_PCT_MAX: Dict[int, float] = {
    1: 100.0,
    2: 40.0,
    3: 20.0,
    4: 0.0,
}

# LEAPS = expiry > 12 months from entry for tier 3 options check
LEAPS_MIN_MONTHS = 12.0

CONVICTION_GRADES = ("A_plus", "A", "B_plus", "B")

# (min_consensus_count for full tier deploy at grade) -> deploy fraction of tier slot
CONVICTION_DEPLOY: Dict[str, Dict[int, float]] = {
    "A_plus": {3: 1.0, 2: 0.5, 1: 0.0, 0: 0.0},
    "A": {3: 0.75, 2: 0.5, 1: 0.0, 0: 0.0},
    "B_plus": {3: 0.5, 2: 0.25, 1: 0.0, 0: 0.0},
    "B": {3: 0.0, 2: 0.0, 1: 0.0, 0: 0.0},
}

# B+ with 2/3 only allowed on tier 1
B_PLUS_TIER_ONLY = 1


@dataclass(frozen=True)
class ExitStep:
    threshold_pct: float
    action: str
    reason_code: str
    priority: str = "high"


# Profit ladders: ascending thresholds; first unmatched fires
TIER_PROFIT_LADDERS: Dict[int, List[ExitStep]] = {
    1: [
        ExitStep(50, "close_all", "tier_1_profit_50", "high"),
        ExitStep(25, "partial_50_breakeven_remainder", "tier_1_profit_25", "high"),
    ],
    2: [
        ExitStep(100, "close_all", "tier_2_profit_100", "high"),
        ExitStep(75, "partial_75_trail_remainder", "tier_2_profit_75", "high"),
        ExitStep(40, "partial_50_breakeven_remainder", "tier_2_profit_40", "high"),
        ExitStep(25, "partial_25_hold_remainder", "tier_2_profit_25", "high"),
    ],
    3: [
        ExitStep(150, "partial_75_hold_remainder", "tier_3_profit_150", "high"),
        ExitStep(75, "partial_50_hold_remainder", "tier_3_profit_75", "high"),
        ExitStep(40, "partial_25_hold_remainder", "tier_3_profit_40", "high"),
    ],
}

TIER_LOSS_LADDERS: Dict[int, List[ExitStep]] = {
    1: [
        ExitStep(-40, "hard_stop", "tier_1_hard_stop_40", "critical"),
        ExitStep(-25, "close_all", "tier_1_stop_25", "critical"),
    ],
    2: [
        ExitStep(-35, "hard_stop", "tier_2_hard_stop_35", "critical"),
        ExitStep(-25, "close_all", "tier_2_stop_25", "critical"),
        ExitStep(-20, "partial_50_reduce", "tier_2_stop_20", "high"),
    ],
    3: [
        ExitStep(-40, "hard_stop", "tier_3_hard_stop_40", "critical"),
        ExitStep(-30, "close_all", "tier_3_stop_30", "critical"),
    ],
}

TIER_TIME_RULES: Dict[int, Dict[str, Any]] = {
    1: {
        "max_hold_days": 28,
        "option_expiry_warn_days": 21,
        "force_exit_reason": "tier_1_max_hold_reached",
    },
    2: {
        "review_interval_days": 30,
        "reduce_at_days": 90,
        "reduce_action": "partial_50_reduce",
        "reduce_reason": "tier_2_no_progress_3mo",
        "max_hold_days": 183,
        "force_decision_reason": "tier_2_max_hold_6mo",
    },
    3: {
        "review_interval_days": 90,
        "defeat_at_days": 183,
        "defeat_down_pct": -30,
        "defeat_reason": "tier_3_down_30_at_6mo",
        "max_hold_days": 365,
        "force_decision_reason": "tier_3_max_hold_12mo",
    },
}

THESIS_EXIT_ACTIONS: Dict[str, Tuple[str, str, str]] = {
    "catalyst_failed": ("close_all", "thesis_catalyst_failed", "critical"),
    "catalyst_denied": ("close_all", "thesis_catalyst_denied", "critical"),
    "thesis_broken": ("close_all", "thesis_fundamentally_broken", "critical"),
    "consensus_broken": ("partial_50_reduce", "thesis_consensus_broken", "high"),
    "stalled": ("partial_50_reduce", "thesis_stalled", "medium"),
}

PROFIT_RECYCLING: Dict[int, List[Tuple[int, float]]] = {
    1: [(1, 0.5), (4, 0.5)],
    2: [(2, 0.4), (3, 0.4), (4, 0.2)],
    3: [(3, 0.5), (2, 0.25), (4, 0.25)],
}

EXIT_ACTION_LABELS: Dict[str, str] = {
    "close_all": "Close entire position",
    "hard_stop": "Hard stop (immediate exit)",
    "partial_50_breakeven_remainder": "Take 50% profit · breakeven stop on remainder",
    "partial_75_trail_remainder": "Take 75% profit · trail remainder",
    "partial_25_hold_remainder": "Take 25% profit · hold remainder",
    "partial_50_hold_remainder": "Take 50% profit · hold remainder",
    "partial_75_hold_remainder": "Take 75% profit · hold remainder",
    "partial_50_reduce": "Reduce position by 50%",
    "force_exit": "Force exit (max hold reached)",
    "decide_roll_or_close": "Decide: roll or close option",
}


def exit_action_label(action: str) -> str:
    return EXIT_ACTION_LABELS.get(action, action.replace("_", " ").title())


def _serialize_exit_steps(steps: List[ExitStep]) -> List[dict[str, Any]]:
    return [
        {
            "threshold_pct": s.threshold_pct,
            "action": s.action,
            "action_label": exit_action_label(s.action),
            "reason_code": s.reason_code,
            "priority": s.priority,
        }
        for s in steps
    ]


def _serialize_time_rules(tier: int, rules: Dict[str, Any]) -> List[dict[str, str]]:
    lines: List[dict[str, str]] = []
    max_days = rules.get("max_hold_days") or TIER_HOLD_DAYS_MAX.get(tier)
    if max_days:
        reason = rules.get("force_exit_reason") or rules.get("force_decision_reason") or f"tier_{tier}_max_hold"
        lines.append({"kind": "max_hold", "label": f"Max hold {max_days} days → force exit ({reason})"})

    if rules.get("option_expiry_warn_days") is not None:
        d = rules["option_expiry_warn_days"]
        lines.append({"kind": "option_expiry", "label": f"Options within {d} days of expiry → roll or close"})

    if rules.get("review_interval_days"):
        lines.append({"kind": "review", "label": f"Review every {rules['review_interval_days']} days"})

    if rules.get("reduce_at_days"):
        action = exit_action_label(rules.get("reduce_action", "partial_50_reduce"))
        lines.append(
            {
                "kind": "reduce",
                "label": f"After {rules['reduce_at_days']} days with stalled thesis → {action}",
            }
        )

    if rules.get("defeat_at_days"):
        down = rules.get("defeat_down_pct", -30)
        lines.append(
            {
                "kind": "defeat",
                "label": f"After {rules['defeat_at_days']} days at {down:+.0f}% P/L → close entire position",
            }
        )

    return lines


def get_tier_exit_logic() -> dict[str, Any]:
    """Serializable tier exit ladders and thesis rules for API/UI."""
    tiers: List[dict[str, Any]] = []
    for tier in DEPLOYABLE_TIERS:
        recycling = [
            {"target_tier": t, "fraction_pct": round(f * 100)}
            for t, f in PROFIT_RECYCLING.get(tier, [])
        ]
        tiers.append(
            {
                "tier": tier,
                "name": tier_display_name(tier),
                "profit_ladder": _serialize_exit_steps(TIER_PROFIT_LADDERS.get(tier, [])),
                "loss_ladder": _serialize_exit_steps(TIER_LOSS_LADDERS.get(tier, [])),
                "time_rules": _serialize_time_rules(tier, TIER_TIME_RULES.get(tier, {})),
                "profit_recycling": recycling,
            }
        )

    thesis_exits = [
        {
            "thesis_status": status.replace("_", " "),
            "action": action,
            "action_label": exit_action_label(action),
            "reason_code": reason,
            "priority": priority,
        }
        for status, (action, reason, priority) in THESIS_EXIT_ACTIONS.items()
    ]

    return {
        "tiers": tiers,
        "thesis_exits": thesis_exits,
        "notes": [
            "Profit and loss ladders evaluate from strictest threshold first; already-fired steps are skipped.",
            "Tier exit logic is defined in tier_config.py and enforced by the daily discipline runner.",
        ],
    }


def tier_budget_pct(rules: dict[str, Any], tier: int) -> float:
    key = f"tier_{tier}_pct" if tier < 4 else "dry_powder_pct"
    return float(rules.get(key, TIER_BUDGET_PCT_DEFAULTS.get(tier, 0)))


def tier_max_positions(rules: dict[str, Any], tier: int) -> int:
    if tier == 4:
        return 0
    return int(rules.get(f"tier_{tier}_max_positions", TIER_MAX_POSITIONS_DEFAULTS.get(tier, 0)))


def tier_display_name(tier: int) -> str:
    return TIER_NAMES.get(tier, f"Tier {tier}")


def tier_slug(tier: int) -> str:
    return TIER_SLUGS.get(tier, f"tier_{tier}")


def tier_hint(tier: int) -> str:
    return TIER_HINTS.get(tier, "")


def get_tier_catalog(rules: Optional[dict[str, Any]] = None) -> List[dict[str, Any]]:
    """Serializable tier legend for API/UI (budget % from rules when provided)."""
    rules = rules or {}
    catalog: List[dict[str, Any]] = []
    for tier in (1, 2, 3, 4):
        pct = tier_budget_pct(rules, tier)
        max_pos = tier_max_positions(rules, tier)
        deployable = tier in DEPLOYABLE_TIERS
        budget_line = (
            f"{pct:.0f}% NAV budget"
            if deployable
            else f"{pct:.0f}% NAV cash reserve"
        )
        positions_line = (
            f"max {max_pos} concurrent positions" if deployable and max_pos else "not deployable"
        )
        catalog.append(
            {
                "id": tier,
                "slug": tier_slug(tier),
                "name": tier_display_name(tier),
                "hint": tier_hint(tier),
                "budget_pct": pct,
                "max_positions": max_pos,
                "deployable": deployable,
                "expected_horizon": TIER_EXPECTED_HORIZON.get(tier),
                "summary": f"{budget_line} · {positions_line} · {tier_hint(tier)}",
            }
        )
    return catalog


def normalize_capital_tier(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        t = int(val)
        return t if 1 <= t <= 4 else None
    except (TypeError, ValueError):
        return None


def infer_capital_tier_from_horizon(horizon: Optional[str]) -> int:
    key = (horizon or "medium").strip().lower()
    return {"short": 1, "medium": 2, "long": 3}.get(key, 2)


def normalize_conviction(val: Any) -> Optional[str]:
    if not val:
        return None
    s = str(val).strip().lower().replace(" ", "_").replace("+", "_plus")
    if s in ("a_plus", "a+", "aplus"):
        return "A_plus"
    if s == "a":
        return "A"
    if s in ("b_plus", "b+", "bplus"):
        return "B_plus"
    if s == "b":
        return "B"
    return None
