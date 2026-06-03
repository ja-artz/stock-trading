"""Daily portfolio NAV from ledger replay + yfinance marks (not only trade snapshots)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from core.benchmarks import DEFAULT_BENCHMARK_SYMBOLS, get_benchmark_closes
from core.db import db_session, row_to_dict
from core.instruments import (
    apply_buy_to_cash,
    apply_sell_to_cash,
    is_option_instrument_type,
    trade_notional,
)
from core.portfolio import compute_nav
from core.pricing import close_on_or_before, get_daily_close_series
from core.snapshots import get_nav_history


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _parse_day(iso_ts: str) -> Optional[date]:
    try:
        raw = iso_ts.replace("Z", "+00:00")
        return datetime.fromisoformat(raw).date()
    except ValueError:
        if len(iso_ts) >= 10:
            return date.fromisoformat(iso_ts[:10])
        return None


def _snapshot_nav_by_day(portfolio_id: int) -> Dict[date, float]:
    """Last stored snapshot NAV per calendar day."""
    by_day: Dict[date, float] = {}
    for row in get_nav_history(portfolio_id, limit=500):
        day = _parse_day(row["as_of"])
        if day:
            by_day[day] = float(row["nav_usd"])
    return by_day


def _trading_days_in_range(start: date, end: date) -> List[date]:
    """Use SPY benchmark calendar as trading-day axis."""
    closes = get_benchmark_closes(DEFAULT_BENCHMARK_SYMBOLS[0], start, end)
    return sorted(closes.keys())


def compute_daily_nav_series(
    portfolio_id: int,
    start: date,
    end: date,
) -> Dict[date, float]:
    """
    One NAV per trading day: replay ledger, mark stocks with historical closes.
    Snapshot NAV for a day wins when present (trade-time book); today uses live marks.
    """
    today = _utc_today()
    snapshot_by_day = _snapshot_nav_by_day(portfolio_id)

    with db_session() as conn:
        port = conn.execute(
            "SELECT initial_cash FROM portfolios WHERE id = ?", (portfolio_id,)
        ).fetchone()
        if not port:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        initial_cash = float(port["initial_cash"])
        trade_rows = conn.execute(
            """
            SELECT * FROM ledger_events
            WHERE portfolio_id = ? AND event_type = 'trade'
            ORDER BY logged_at, id
            """,
            (portfolio_id,),
        ).fetchall()

    trades = [row_to_dict(r) for r in trade_rows]
    if not trades and not snapshot_by_day:
        return {end: float(compute_nav(portfolio_id)["nav_usd"])}

    first_activity = start
    for t in trades:
        d = _parse_day(t.get("logged_at") or "")
        if d and d < first_activity:
            first_activity = d
    if snapshot_by_day:
        first_snap = min(snapshot_by_day)
        if first_snap < first_activity:
            first_activity = first_snap

    trading_days = _trading_days_in_range(first_activity, end)
    if not trading_days:
        trading_days = [end]

    tickers: Set[str] = set()
    for t in trades:
        tickers.add((t.get("ticker") or "").upper())

    close_by_ticker: Dict[str, Dict[date, float]] = {}
    for sym in tickers:
        if sym:
            close_by_ticker[sym] = get_daily_close_series(sym, first_activity - timedelta(days=7), end)

    cash = initial_cash
    holdings: Dict[str, dict] = {}
    trade_i = 0
    marked: Dict[date, float] = {}

    for day in trading_days:
        while trade_i < len(trades):
            t = trades[trade_i]
            trade_day = _parse_day(t.get("logged_at") or "")
            if trade_day is None or trade_day > day:
                break
            side = (t.get("side") or "").lower()
            ticker = (t.get("ticker") or "").upper()
            inst = t.get("instrument_type") or "stock"
            qty = float(t["quantity"])
            price = float(t["price"])
            fees = float(t.get("fees") or 0)
            key = f"{ticker}:{inst}"

            if key not in holdings:
                holdings[key] = {
                    "ticker": ticker,
                    "instrument_type": inst,
                    "quantity": 0.0,
                    "cost_basis_total": 0.0,
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
            trade_i += 1

        if day == today:
            nav = float(compute_nav(portfolio_id)["nav_usd"])
        elif day in snapshot_by_day:
            nav = snapshot_by_day[day]
        else:
            invested = 0.0
            for h in holdings.values():
                qty = h["quantity"]
                if qty <= 1e-9:
                    continue
                inst = h["instrument_type"]
                if is_option_instrument_type(inst):
                    invested += h["cost_basis_total"]
                else:
                    sym = h["ticker"]
                    px = close_on_or_before(close_by_ticker.get(sym, {}), day)
                    if px is None or px <= 0:
                        px = h["cost_basis_total"] / qty if qty else 0.0
                    invested += px * qty
            nav = round(cash + invested, 2)

        marked[day] = nav

    return marked


def daily_nav_for_period(
    portfolio_id: int,
    start: Optional[date],
    end: date,
) -> Dict[date, float]:
    """NAV keyed by date within [start, end] (inclusive)."""
    range_start = start or (end - timedelta(days=30))
    series = compute_daily_nav_series(portfolio_id, range_start, end)
    return {d: v for d, v in series.items() if d <= end and (start is None or d >= start)}
