"""Normalize trader-agent sizing fields for persistence and display."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from core.rules import is_option_instrument


def _num(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def normalize_plan_item_sizing(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten sizing object onto item and ensure sizing_summary for UI."""
    sizing = item.get("sizing")
    if isinstance(sizing, dict):
        item.setdefault("suggested_notional_usd", _num(sizing.get("notional_usd")))
        item.setdefault("suggested_quantity", _num(sizing.get("quantity")))
        item.setdefault("quantity_unit", sizing.get("quantity_unit"))
        item.setdefault("pct_nav", _num(sizing.get("pct_nav")))
        item.setdefault("pct_cash", _num(sizing.get("pct_cash")))
        item.setdefault("pct_position", _num(sizing.get("pct_position")))
        item.setdefault("sizing_summary", sizing.get("summary"))

    item["suggested_notional_usd"] = _num(item.get("suggested_notional_usd"))
    item["suggested_quantity"] = _num(item.get("suggested_quantity"))
    item["pct_nav"] = _num(item.get("pct_nav"))
    item["pct_cash"] = _num(item.get("pct_cash"))
    item["pct_position"] = _num(item.get("pct_position"))

    unit = item.get("quantity_unit")
    if unit and isinstance(unit, str):
        item["quantity_unit"] = unit.strip().lower()

    summary = (item.get("sizing_summary") or "").strip()
    if not summary:
        summary = _build_sizing_summary(item)
    item["sizing_summary"] = summary or None
    return item


def _build_sizing_summary(item: dict[str, Any]) -> str:
    action = (item.get("action") or "").lower()
    parts: list[str] = []

    notional = item.get("suggested_notional_usd")
    qty = item.get("suggested_quantity")
    unit = item.get("quantity_unit") or "shares"

    if action in ("watch", "hold") and not notional and not qty:
        return "No size — monitor only"

    if notional is not None and notional > 0:
        parts.append(f"${notional:,.0f}")
    if qty is not None and qty > 0:
        label = "contracts" if unit == "contracts" else "shares"
        q = int(qty) if qty == int(qty) else qty
        parts.append(f"{q} {label}")

    pct_pos = item.get("pct_position")
    if pct_pos is not None and action in ("trim", "sell"):
        parts.append(f"{pct_pos:.0f}% of position")

    if not parts:
        hint = item.get("size_hint")
        if hint:
            return f"Qualitative: {hint}"
        return ""

    line = " · ".join(parts)
    extras: list[str] = []
    if item.get("pct_cash") is not None:
        extras.append(f"{item['pct_cash']:.0f}% of cash")
    if item.get("pct_nav") is not None:
        extras.append(f"{item['pct_nav']:.0f}% of NAV")
    if extras:
        line += f" ({', '.join(extras)})"
    return line


def reconcile_stock_sizing_with_quote(
    item: dict[str, Any],
    price_usd: float,
    nav_state: dict[str, Any],
) -> dict[str, Any]:
    """Align stock sizing fields and summary with a live per-share quote."""
    inst = (item.get("instrument_type") or "stock").lower()
    if is_option_instrument(inst):
        return item

    action = (item.get("action") or "").lower()
    if action in ("watch", "hold"):
        return item

    ticker = (item.get("ticker") or "").strip().upper()
    if not ticker or price_usd <= 0:
        return item

    nav = float(nav_state.get("nav_usd") or 0)
    cash = float(nav_state.get("cash_usd") or 0)

    notional = item.get("suggested_notional_usd")
    qty = item.get("suggested_quantity")
    pct_nav = item.get("pct_nav")
    pct_cash = item.get("pct_cash")

    if action in ("buy", "hedge"):
        if pct_cash is not None and cash > 0:
            notional = cash * float(pct_cash) / 100.0
        elif (notional is None or notional <= 0) and pct_nav is not None and nav > 0:
            notional = nav * float(pct_nav) / 100.0

    if notional is not None and notional > 0:
        if action in ("buy", "hedge"):
            qty = max(1, int(math.floor(float(notional) / price_usd + 0.5)))
        notional = round(float(qty or 0) * price_usd, 2) if qty else None
    elif qty is not None and float(qty) > 0:
        notional = round(float(qty) * price_usd, 2)
    else:
        return item

    item["suggested_notional_usd"] = notional
    item["suggested_quantity"] = float(qty) if qty is not None else None
    item["quantity_unit"] = "shares"
    item["quote_price_usd"] = round(price_usd, 4)

    summary = _summary_with_live_price(item, price_usd, notional, qty)
    item["sizing_summary"] = summary
    sizing = item.get("sizing")
    if isinstance(sizing, dict):
        sizing["notional_usd"] = notional
        sizing["quantity"] = qty
        sizing["summary"] = summary
        sizing["price_usd"] = round(price_usd, 4)

    return item


def _summary_with_live_price(
    item: dict[str, Any],
    price_usd: float,
    notional: Optional[float],
    qty: Optional[float],
) -> str:
    action = (item.get("action") or "").lower()
    verb = "Buy" if action in ("buy", "hedge") else "Sell" if action in ("sell", "trim") else "Trade"
    parts: list[str] = []
    if notional is not None and notional > 0 and qty is not None and qty > 0:
        q = int(qty) if qty == int(qty) else qty
        line = f"{verb} ~${notional:,.0f} ({q} share{'s' if q != 1 else ''} @ ~${price_usd:,.2f})"
    elif notional is not None and notional > 0:
        line = f"{verb} ~${notional:,.0f} @ ~${price_usd:,.2f}/share"
    elif qty is not None and qty > 0:
        q = int(qty) if qty == int(qty) else qty
        line = f"{verb} {q} share{'s' if q != 1 else ''} @ ~${price_usd:,.2f}"
    else:
        line = f"{verb} @ ~${price_usd:,.2f}/share"
    extras: list[str] = []
    if item.get("pct_cash") is not None:
        extras.append(f"{item['pct_cash']:.0f}% of cash")
    if item.get("pct_nav") is not None:
        extras.append(f"{item['pct_nav']:.0f}% of NAV")
    if extras:
        line += f" ({', '.join(extras)})"
    return line
