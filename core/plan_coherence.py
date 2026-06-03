"""Horizon vs option-expiry coherence checks for weekly plan items."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, List, Optional, Tuple

# Thesis window (months from plan date) by horizon label
HORIZON_THESIS_MONTHS: dict[str, Tuple[float, float]] = {
    "short": (0.5, 2.0),
    "medium": (2.0, 5.0),
    "long": (6.0, 18.0),
}

# Max months from plan date to option expiry (after thesis end), by horizon
HORIZON_MAX_EXPIRY_MONTHS: dict[str, float] = {
    "short": 3.0,
    "medium": 7.0,
    "long": 20.0,
}


def _parse_date(val: Any) -> Optional[date]:
    if not val:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    s = str(val).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _months_apart(start: date, end: date) -> float:
    return max(0.0, (end - start).days / 30.44)


def _thesis_bounds(horizon: Optional[str]) -> Tuple[float, float]:
    key = (horizon or "medium").strip().lower()
    return HORIZON_THESIS_MONTHS.get(key, HORIZON_THESIS_MONTHS["medium"])


def normalize_option_contract(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten option_contract onto item for validation and display."""
    oc = item.get("option_contract")
    if not isinstance(oc, dict):
        return item
    item.setdefault("option_expiry", oc.get("expiry"))
    item.setdefault("option_strike", oc.get("strike"))
    item.setdefault("option_right", oc.get("right"))
    item.setdefault("option_moneyness", oc.get("moneyness"))
    if oc.get("underlying"):
        item.setdefault("ticker", item.get("ticker") or oc.get("underlying"))
    return item


def check_plan_item_coherence(item: dict[str, Any], plan_as_of: date) -> List[str]:
    """Return human-readable warnings for horizon / expiry / thesis mismatches."""
    warnings: List[str] = []
    inst = (item.get("instrument_type") or "").lower()
    is_option = "option" in inst or inst in ("call", "put")

    horizon = item.get("horizon")
    thesis_min, thesis_max = _thesis_bounds(horizon)

    exit_months = item.get("expected_exit_months")
    if exit_months is not None:
        try:
            em = float(exit_months)
            if em > thesis_max + 0.5:
                warnings.append(
                    f"expected_exit_months ({em:.1f}) exceeds horizon '{horizon}' thesis window "
                    f"({thesis_min:.0f}–{thesis_max:.0f} mo) — align horizon or exit estimate"
                )
            if em < thesis_min - 0.25:
                warnings.append(
                    f"expected_exit_months ({em:.1f}) is shorter than horizon '{horizon}' "
                    f"({thesis_min:.0f}–{thesis_max:.0f} mo)"
                )
            thesis_max = min(thesis_max, em + 1.0)
        except (TypeError, ValueError):
            pass

    if not is_option:
        return warnings

    expiry = _parse_date(item.get("option_expiry") or (item.get("option_contract") or {}).get("expiry"))
    if not expiry:
        # Try YYYY-MM from sizing summary
        summary = (item.get("sizing_summary") or "") + " " + (item.get("rationale") or "")
        m = re.search(r"\b(20\d{2})-(\d{2})(?:-(\d{2}))?\b", summary)
        if m:
            day = m.group(3) or "15"
            expiry = _parse_date(f"{m.group(1)}-{m.group(2)}-{day}")
        else:
            m = re.search(
                r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b",
                summary,
                re.I,
            )
            if m:
                months = {
                    "jan": 1,
                    "feb": 2,
                    "mar": 3,
                    "apr": 4,
                    "may": 5,
                    "jun": 6,
                    "jul": 7,
                    "aug": 8,
                    "sep": 9,
                    "oct": 10,
                    "nov": 11,
                    "dec": 12,
                }
                mo = months.get(m.group(1).lower()[:3], 1)
                expiry = date(int(m.group(2)), mo, 15)

    if not expiry:
        warnings.append(
            "Option line missing option_contract.expiry (YYYY-MM-DD) — add explicit expiry for Sofi execution"
        )
        return warnings

    months_to_expiry = _months_apart(plan_as_of, expiry)
    hkey = (horizon or "medium").strip().lower()
    max_exp = HORIZON_MAX_EXPIRY_MONTHS.get(hkey, 7.0)

    if months_to_expiry > max_exp:
        warnings.append(
            f"Option expiry {expiry.isoformat()} is ~{months_to_expiry:.0f} months out, but horizon "
            f"'{horizon}' implies a ~{thesis_min:.0f}–{thesis_max:.0f} month thesis — use a nearer expiry "
            f"(typically <={max_exp:.0f} months from plan date) unless horizon is 'long'"
        )

    if months_to_expiry < thesis_min:
        warnings.append(
            f"Option expiry {expiry.isoformat()} (~{months_to_expiry:.1f} mo) is shorter than the "
            f"'{horizon}' thesis window ({thesis_min:.0f}–{thesis_max:.0f} mo) — may expire before catalyst"
        )

    # Expiry far past expected exit (e.g. 3–4 mo thesis, Jan 2027 LEAPS)
    thesis_end_mo = thesis_max
    if exit_months is not None:
        try:
            thesis_end_mo = float(exit_months)
        except (TypeError, ValueError):
            pass
    if months_to_expiry > thesis_end_mo + 3.0:
        warnings.append(
            f"Option expiry is ~{months_to_expiry:.0f} mo out vs ~{thesis_end_mo:.0f} mo expected exit — "
            "likely over-paying for time (LEAPS); match expiry to thesis + ~1–2 months buffer"
        )

    return warnings


def apply_plan_item_coherence(item: dict[str, Any], plan_as_of: date) -> dict[str, Any]:
    """Normalize option fields and merge coherence warnings into rule_warnings."""
    from core.tier_engine import check_tier_horizon_coherence

    item = normalize_option_contract(item)
    new_warnings = check_plan_item_coherence(item, plan_as_of)
    new_warnings.extend(
        check_tier_horizon_coherence(
            item.get("capital_tier"),
            item.get("horizon"),
            item.get("expected_exit_months"),
        )
    )
    if not new_warnings:
        return item
    existing = item.get("rule_warnings")
    if isinstance(existing, list):
        merged = list(existing)
    elif existing:
        merged = [str(existing)]
    else:
        merged = []
    for w in new_warnings:
        if w not in merged:
            merged.append(w)
    item["rule_warnings"] = merged
    return item
