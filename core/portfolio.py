"""Portfolio state from ledger."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from core.db import db_session, row_to_dict
from core.instruments import (
    OPTION_CONTRACT_MULTIPLIER,
    apply_buy_to_cash,
    apply_sell_to_cash,
    find_open_position,
    is_option_instrument_type,
    normalize_expiry,
    position_key,
    trade_notional,
)
from core.pricing import clear_option_chain_cache, get_last_price, get_option_mark_for_position
from core import store
from core.rules import is_option_instrument


def _holding_key_from_event(ev: dict) -> str:
    return position_key(
        ev.get("ticker") or "",
        ev.get("instrument_type") or "stock",
        strike=ev.get("strike"),
        expiry=ev.get("expiry"),
    )


def _mark_option_position(h: dict) -> tuple[float, str, Optional[str]]:
    """Return (premium_per_share, mark_source, quote_as_of)."""
    qty = float(h.get("quantity") or 0)
    cost_total = float(h.get("cost_basis_total") or 0)
    fallback = cost_total / (qty * OPTION_CONTRACT_MULTIPLIER) if qty else 0.0

    mark_info = get_option_mark_for_position(h)
    quote = mark_info.get("premium_per_share")
    if quote is not None and float(quote) > 0:
        fetched_at = mark_info.get("fetched_at")
        return float(quote), "live", str(fetched_at) if fetched_at else None

    return fallback, "cost", None


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
        event_type = (ev.get("event_type") or "trade").lower()
        if event_type == "cash_deposit":
            cash += float(ev["quantity"])
            continue
        if event_type != "trade":
            continue

        side = ev["side"].lower()
        ticker = ev["ticker"].upper()
        qty = float(ev["quantity"])
        price = float(ev["price"])
        fees = float(ev.get("fees") or 0)
        inst = ev.get("instrument_type") or "stock"
        key = _holding_key_from_event(ev)

        if key not in holdings:
            holdings[key] = {
                "ticker": ticker,
                "instrument_type": inst,
                "quantity": 0.0,
                "cost_basis_total": 0.0,
                "strike": ev.get("strike"),
                "expiry": normalize_expiry(ev.get("expiry")),
            }
        h = holdings[key]
        if side == "buy":
            cash = apply_buy_to_cash(cash, qty, price, inst, fees)
            h["cost_basis_total"] += trade_notional(qty, price, inst)
            h["quantity"] += qty
            if h.get("strike") is None and ev.get("strike") is not None:
                h["strike"] = ev.get("strike")
            if not h.get("expiry") and ev.get("expiry"):
                h["expiry"] = normalize_expiry(ev.get("expiry"))
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

        quote_as_of: Optional[str] = None
        if is_option_instrument_type(inst):
            mark, mark_source, quote_as_of = _mark_option_position(h)
            market_value = mark * qty * OPTION_CONTRACT_MULTIPLIER
            avg_cost_display = cost_total / qty if qty else 0.0
        else:
            mark = get_last_price(h["ticker"]) or 0.0
            mark_source = "live" if mark > 0 else "cost"
            if mark > 0:
                quote_as_of = store.utc_now_iso()
            if mark <= 0 and qty > 0:
                mark = cost_total / qty
            market_value = mark * qty
            avg_cost_display = cost_total / qty if qty else 0.0

        unrealized_pnl = round(market_value - cost_total, 2)
        cost_basis = round(cost_total, 2)
        pnl_pct = round(unrealized_pnl / cost_basis * 100, 2) if cost_basis > 0 else 0.0
        positions.append(
            {
                "ticker": h["ticker"],
                "instrument_type": inst,
                "quantity": qty,
                "avg_cost": avg_cost_display,
                "mark_price": mark,
                "mark_source": mark_source,
                "quote_as_of": quote_as_of,
                "market_value": round(market_value, 2),
                "cost_basis": cost_basis,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": pnl_pct,
                "strike": h.get("strike"),
                "expiry": h.get("expiry"),
                "is_option": is_option_instrument_type(inst),
                "option_quote_available": mark_source == "live",
            }
        )
    return cash, positions


def compute_nav(portfolio_id: int) -> dict:
    clear_option_chain_cache()
    cash, positions = compute_positions_from_ledger(portfolio_id)
    invested = sum(p.get("market_value", 0) for p in positions)
    nav = cash + invested
    cash_pct = (cash / nav * 100) if nav > 0 else 100.0
    unrealized_pnl = round(sum(p.get("unrealized_pnl", 0) for p in positions), 2)
    cost_basis = sum(p.get("cost_basis", 0) for p in positions)
    unrealized_pnl_pct = round(unrealized_pnl / cost_basis * 100, 2) if cost_basis > 0 else 0.0
    return {
        "cash_usd": round(cash, 2),
        "nav_usd": round(nav, 2),
        "invested_usd": round(invested, 2),
        "cash_pct": round(cash_pct, 2),
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "positions": positions,
    }


def is_new_position(
    portfolio_id: int,
    ticker: str,
    instrument_type: str = "stock",
    *,
    strike: Optional[float] = None,
    expiry: Optional[str] = None,
) -> bool:
    _, positions = compute_positions_from_ledger(portfolio_id)
    pos = find_open_position(
        positions,
        ticker,
        instrument_type,
        strike=strike,
        expiry=expiry,
    )
    return not (pos and abs(pos.get("quantity", 0)) > 0)


def open_option_count(positions: List[dict]) -> int:
    return sum(
        1 for p in positions
        if is_option_instrument(p.get("instrument_type", "stock")) and abs(p.get("quantity", 0)) > 0
    )
