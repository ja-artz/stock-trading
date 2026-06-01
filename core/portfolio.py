"""Portfolio state from ledger."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from core.db import db_session, row_to_dict
from core.pricing import get_last_price
from core.rules import is_option_instrument


def _empty_positions() -> List[dict]:
    return []


def compute_positions_from_ledger(portfolio_id: int) -> Tuple[float, List[dict]]:
    """Return (cash_usd, positions list with mark_price)."""
    with db_session() as conn:
        port = conn.execute("SELECT initial_cash FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        if not port:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        cash = float(port["initial_cash"])
        rows = conn.execute(
            """
            SELECT * FROM ledger_events WHERE portfolio_id = ?
            ORDER BY logged_at, id
            """,
            (portfolio_id,),
        ).fetchall()

    holdings: Dict[str, dict] = {}
    for row in rows:
        ev = row_to_dict(row)
        side = ev["side"].lower()
        ticker = ev["ticker"].upper()
        qty = float(ev["quantity"])
        price = float(ev["price"])
        fees = float(ev.get("fees") or 0)
        inst = ev.get("instrument_type") or "stock"
        key = f"{ticker}:{inst}"

        if key not in holdings:
            holdings[key] = {
                "ticker": ticker,
                "instrument_type": inst,
                "quantity": 0.0,
                "cost_basis_total": 0.0,
                "strike": ev.get("strike"),
                "expiry": ev.get("expiry"),
            }
        h = holdings[key]
        if side == "buy":
            cash -= qty * price + fees
            h["cost_basis_total"] += qty * price
            h["quantity"] += qty
        elif side == "sell":
            cash += qty * price - fees
            h["quantity"] -= qty
            if h["quantity"] <= 1e-9:
                h["quantity"] = 0.0
                h["cost_basis_total"] = 0.0

    positions: List[dict] = []
    for h in holdings.values():
        if abs(h["quantity"]) < 1e-9:
            continue
        mark = get_last_price(h["ticker"]) or 0.0
        if is_option_instrument(h["instrument_type"]):
            mark = mark * 100 * abs(h["quantity"]) / max(abs(h["quantity"]), 1)
        avg_cost = h["cost_basis_total"] / h["quantity"] if h["quantity"] else 0.0
        market_value = mark * h["quantity"] if not is_option_instrument(h["instrument_type"]) else mark
        positions.append(
            {
                "ticker": h["ticker"],
                "instrument_type": h["instrument_type"],
                "quantity": h["quantity"],
                "avg_cost": avg_cost,
                "mark_price": mark,
                "market_value": market_value,
                "strike": h.get("strike"),
                "expiry": h.get("expiry"),
            }
        )
    return cash, positions


def compute_nav(portfolio_id: int) -> dict:
    cash, positions = compute_positions_from_ledger(portfolio_id)
    invested = sum(p.get("market_value", 0) for p in positions)
    nav = cash + invested
    cash_pct = (cash / nav * 100) if nav > 0 else 100.0
    return {
        "cash_usd": round(cash, 2),
        "nav_usd": round(nav, 2),
        "invested_usd": round(invested, 2),
        "cash_pct": round(cash_pct, 2),
        "positions": positions,
    }


def is_new_position(portfolio_id: int, ticker: str) -> bool:
    cash, positions = compute_positions_from_ledger(portfolio_id)
    for p in positions:
        if p["ticker"].upper() == ticker.upper() and abs(p["quantity"]) > 1e-9:
            return False
    return True


def open_option_count(positions: List[dict]) -> int:
    return sum(
        1 for p in positions
        if is_option_instrument(p.get("instrument_type", "stock")) and abs(p.get("quantity", 0)) > 0
    )
