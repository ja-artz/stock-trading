"""Execute trader plan items against a paper book at historical prices."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.paper_book import PaperBook
from backtest.returns import _price_on
from core.plan_sizing import normalize_plan_item_sizing
from core.rules import is_option_instrument
from validation import lookup_ticker_yfinance


def _actionable_items(plan: dict) -> List[dict]:
    if plan.get("no_changes") and not plan.get("items"):
        return []
    items = []
    for raw in plan.get("items") or []:
        item = normalize_plan_item_sizing(dict(raw))
        action = (item.get("action") or "").lower()
        if action in ("watch", "hold"):
            continue
        ticker = (item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        inst = (item.get("instrument_type") or "stock").lower()
        if is_option_instrument(inst):
            continue
        if not lookup_ticker_yfinance(ticker).get("valid"):
            continue
        items.append(item)
    return items


def execute_plan_on_book(
    book: PaperBook,
    plan: dict,
    *,
    trade_date: date,
    close: pd.DataFrame,
) -> List[dict]:
    """Apply all accepted trader line items at trade_date close. Returns execution log."""
    logs: List[dict] = []
    for item in _actionable_items(plan):
        sym = item["ticker"].upper()
        price = _price_on(close, sym, trade_date)
        if not price or price <= 0:
            logs.append({"ticker": sym, "action": item["action"], "ok": False, "reason": "no_price"})
            continue
        action = (item["action"] or "").lower()
        ok = False
        if action == "buy":
            notional = item.get("suggested_notional_usd")
            nav = book.mark_nav({sym: price})
            if notional is None and item.get("pct_nav"):
                notional = nav * float(item["pct_nav"]) / 100.0
            if notional is None and item.get("pct_cash"):
                notional = book.cash_usd * float(item["pct_cash"]) / 100.0
            if notional is None:
                qty = item.get("suggested_quantity")
                notional = float(qty) * price if qty else nav / max(len(_actionable_items(plan)), 1) * 0.1
            ok = book.apply_buy(sym, float(notional), price)
        elif action in ("sell", "trim"):
            ok = book.apply_sell(
                sym,
                price,
                pct_position=item.get("pct_position"),
                quantity=item.get("suggested_quantity"),
            )
        elif action == "hedge":
            ok = book.apply_buy(sym, min(book.cash_usd * 0.15, book.cash_usd), price)
        logs.append(
            {
                "ticker": sym,
                "action": action,
                "ok": ok,
                "price": round(price, 4),
                "trade_date": trade_date.isoformat(),
            }
        )
    return logs


def plan_items_for_report(plan: dict) -> List[dict]:
    return [
        {
            "action": i.get("action"),
            "ticker": i.get("ticker"),
            "instrument_type": i.get("instrument_type"),
            "sizing_summary": i.get("sizing_summary"),
            "thesis_type": i.get("thesis_type"),
        }
        for i in _actionable_items(plan)
    ]
