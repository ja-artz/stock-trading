"""Lightweight tier exit snapshot for weekly backtest (no position_lots DB)."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from core.tier_config import infer_capital_tier_from_horizon, normalize_capital_tier
from core.tier_engine import ActionItemDraft, evaluate_position_exits


def snapshot_paper_discipline(
    positions: List[dict],
    plan_items: List[dict],
    as_of: date,
) -> List[dict[str, Any]]:
    """Return would-have discipline actions for paper book holdings."""
    tier_by_ticker: Dict[str, int] = {}
    for item in plan_items:
        t = (item.get("ticker") or "").strip().upper()
        if not t:
            continue
        tier = normalize_capital_tier(item.get("capital_tier"))
        if tier is None:
            tier = infer_capital_tier_from_horizon(item.get("horizon"))
        tier_by_ticker[t] = tier or 2

    out: List[dict[str, Any]] = []
    for pos in positions:
        ticker = (pos.get("ticker") or "").upper()
        if not ticker:
            continue
        lot = {
            "id": None,
            "ticker": ticker,
            "instrument_type": pos.get("instrument_type", "stock"),
            "capital_tier": tier_by_ticker.get(ticker, 2),
            "entry_date": pos.get("entry_date") or as_of.isoformat(),
            "entry_price": float(pos.get("avg_cost") or pos.get("mark_price") or 0),
            "partial_exits_json": "[]",
            "thesis_status": "active",
            "expiry": pos.get("expiry"),
        }
        mark = float(pos.get("mark_price") or lot["entry_price"])
        for draft in evaluate_position_exits(lot, mark_price=mark, as_of=as_of):
            out.append(
                {
                    "ticker": draft.ticker,
                    "priority": draft.priority,
                    "action": draft.action,
                    "reason_code": draft.reason_code,
                    "detail": draft.detail,
                }
            )
    return out
