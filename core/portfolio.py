"""Portfolio state from ledger."""

from __future__ import annotations

from typing import Dict, List, Tuple

from core.db import db_session, row_to_dict
from core.instruments import (
    OPTION_CONTRACT_MULTIPLIER,
    apply_buy_to_cash,
    apply_sell_to_cash,
    is_option_instrument_type,
    trade_notional,
)
from core.pricing import get_last_price
from core.rules import is_option_instrument


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
            cash = apply_buy_to_cash(cash, qty, price, inst, fees)
            h["cost_basis_total"] += trade_notional(qty, price, inst)
            h["quantity"] += qty
        elif side == "sell":
            cash = apply_sell_to_cash(cash, qty, price, inst, fees)
            if h["quantity"] > 1e-9:
                sold_frac = min(1.0, qty / h["quantity"])
                h["cost_basis_total"] *= 1.0 - sold_frac
            h["quantity"] -= qty
            if h["quantity"] <= 1e-9:
                h["quantity"] = 0.0
                h["cost_basis_total"] = 0.0

    positions: List[dict] = []
    for h in holdings.values():
        if abs(h["quantity"]) < 1e-9:
            continue
        qty = h["quantity"]
        cost_total = h["cost_basis_total"]
        inst = h["instrument_type"]

        if is_option_instrument_type(inst):
            # Paper book: mark options at cost (premium paid) until we have option quotes.
            premium_per_share = cost_total / (qty * OPTION_CONTRACT_MULTIPLIER) if qty else 0.0
            mark = premium_per_share
            market_value = cost_total
            avg_cost_display = cost_total / qty if qty else 0.0
        else:
            mark = get_last_price(h["ticker"]) or 0.0
            if mark <= 0 and qty > 0:
                mark = cost_total / qty
            market_value = mark * qty
            avg_cost_display = cost_total / qty if qty else 0.0

        positions.append(
            {
                "ticker": h["ticker"],
                "instrument_type": inst,
                "quantity": qty,
                "avg_cost": avg_cost_display,
                "mark_price": mark,
                "market_value": market_value,
                "strike": h.get("strike"),
                "expiry": h.get("expiry"),
                "is_option": is_option_instrument_type(inst),
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
    _, positions = compute_positions_from_ledger(portfolio_id)
    for p in positions:
        if p["ticker"].upper() == ticker.upper() and abs(p["quantity"]) > 0:
            return False
    return True


def open_option_count(positions: List[dict]) -> int:
    return sum(
        1 for p in positions
        if is_option_instrument(p.get("instrument_type", "stock")) and abs(p.get("quantity", 0)) > 0
    )
