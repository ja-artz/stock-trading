"""Position drill-down: trades and value history."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from core.db import db_session, row_to_dict
from core.instruments import (
    find_open_position,
    is_option_instrument_type,
    normalize_expiry,
    position_key,
    trade_notional,
)
from core.portfolio import compute_nav
from core.pricing import close_on_or_before, get_daily_close_series
from core.ticker_names import company_name_for


def _days_since(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    try:
        raw = iso_ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        purchase_day = dt.astimezone(timezone.utc).date()
        today = datetime.now(timezone.utc).date()
        return max(0, (today - purchase_day).days)
    except ValueError:
        return None


def _day_key(iso_ts: str) -> str:
    return iso_ts[:10] if len(iso_ts) >= 10 else iso_ts


def _parse_day(iso_ts: str) -> date | None:
    try:
        raw = iso_ts.replace("Z", "+00:00")
        return datetime.fromisoformat(raw).date()
    except ValueError:
        if len(iso_ts) >= 10:
            return date.fromisoformat(iso_ts[:10])
        return None


def _quantity_on_day(trades: list[dict[str, Any]], day: date) -> float:
    qty = 0.0
    for trade in trades:
        trade_day = _parse_day(trade.get("logged_at") or "")
        if trade_day is None or trade_day > day:
            continue
        side = (trade.get("side") or "").lower()
        amount = float(trade.get("quantity") or 0)
        if side == "buy":
            qty += amount
        elif side == "sell":
            qty -= amount
    return qty


def _day_iso(day: date) -> str:
    return f"{day.isoformat()}T16:00:00+00:00"


def _build_value_history(
    position: dict[str, Any],
    trades: list[dict[str, Any]],
    first_purchase: str | None,
    cost_basis: float,
    current_mv: float,
    snap_rows: list,
) -> list[dict[str, Any]]:
    """One mark per calendar day from purchase through today."""
    sym = position["ticker"]
    inst = position["instrument_type"]
    today = datetime.now(timezone.utc).date()
    rounded_mv = round(current_mv, 2)
    pos_key = position_key(sym, inst, strike=position.get("strike"), expiry=position.get("expiry"))

    if not first_purchase:
        return [{"as_of": datetime.now(timezone.utc).isoformat(), "market_value": rounded_mv}]

    start_day = _parse_day(first_purchase)
    if start_day is None:
        start_day = today

    snapshot_by_day: dict[str, float] = {}
    for snap in snap_rows:
        positions_at = json.loads(snap["positions_json"] or "[]")
        for p in positions_at:
            p_key = position_key(
                p.get("ticker") or "",
                p.get("instrument_type") or "stock",
                strike=p.get("strike"),
                expiry=p.get("expiry"),
            )
            if p_key == pos_key:
                snapshot_by_day[_day_key(snap["as_of"])] = round(float(p.get("market_value") or 0), 2)
                break

    history: list[dict[str, Any]] = []
    closes: dict[date, float] = {}
    if not is_option_instrument_type(inst):
        closes = get_daily_close_series(sym, start_day, today)

    day = start_day
    while day <= today:
        day_key = day.isoformat()
        qty = _quantity_on_day(trades, day)
        if qty <= 1e-9:
            day += timedelta(days=1)
            continue

        if day == today:
            mv = rounded_mv
            source = position.get("mark_source") or "live"
        elif day_key in snapshot_by_day:
            mv = snapshot_by_day[day_key]
            source = "snapshot"
        elif day == start_day:
            mv = round(cost_basis, 2)
            source = "cost_basis"
        elif is_option_instrument_type(inst):
            mv = round(cost_basis, 2)
            source = "cost_basis"
        else:
            close = close_on_or_before(closes, day)
            if close is not None:
                mv = round(close * qty, 2)
                source = "close"
            else:
                mv = round(cost_basis, 2)
                source = "cost_basis"

        history.append({"as_of": _day_iso(day), "market_value": mv, "mark_source": source})
        day += timedelta(days=1)

    return history


def _trade_matches_contract(ev: dict[str, Any], strike: Any, expiry: Any) -> bool:
    if strike is None and not expiry:
        return True
    if strike is not None and ev.get("strike") is not None:
        try:
            if abs(float(ev["strike"]) - float(strike)) > 0.01:
                return False
        except (TypeError, ValueError):
            return False
    elif strike is not None and ev.get("strike") is None:
        return False
    if expiry and ev.get("expiry"):
        if normalize_expiry(ev.get("expiry")) != normalize_expiry(expiry):
            return False
    elif expiry and not ev.get("expiry"):
        return False
    return True


def get_position_detail(
    portfolio_id: int,
    ticker: str,
    instrument_type: str = "stock",
    *,
    strike: float | None = None,
    expiry: str | None = None,
) -> dict[str, Any]:
    sym = ticker.strip().upper()
    inst = (instrument_type or "stock").strip().lower()
    state = compute_nav(portfolio_id)
    position = find_open_position(state["positions"], sym, inst, strike=strike, expiry=expiry)
    if not position:
        raise ValueError(f"No open position for {sym} ({inst})")

    contract_strike = position.get("strike") if strike is None else strike
    contract_expiry = position.get("expiry") if expiry is None else normalize_expiry(expiry)

    with db_session() as conn:
        trade_rows = conn.execute(
            """
            SELECT * FROM ledger_events
            WHERE portfolio_id = ? AND ticker = ? AND instrument_type = ?
            ORDER BY logged_at, id
            """,
            (portfolio_id, sym, inst),
        ).fetchall()
        port_row = conn.execute("SELECT name FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        snap_rows = conn.execute(
            """
            SELECT as_of, positions_json FROM snapshots
            WHERE portfolio_id = ?
            ORDER BY as_of ASC
            """,
            (portfolio_id,),
        ).fetchall()

    trades: list[dict[str, Any]] = []
    buy_dates: list[str] = []
    for row in trade_rows:
        ev = row_to_dict(row)
        if is_option_instrument_type(inst) and not _trade_matches_contract(
            ev, contract_strike, contract_expiry
        ):
            continue
        qty = float(ev["quantity"])
        price = float(ev["price"])
        fees = float(ev.get("fees") or 0)
        notional = trade_notional(qty, price, inst)
        side = ev["side"].lower()
        if side == "buy" and ev.get("logged_at"):
            buy_dates.append(ev["logged_at"])
        trades.append(
            {
                **ev,
                "total": round(notional, 2),
                "fees": fees,
            }
        )

    first_purchase = min(buy_dates) if buy_dates else None

    current_mv = float(position.get("market_value") or 0)
    cost_basis = round(float(position.get("cost_basis") or current_mv), 2)
    value_history = _build_value_history(
        position,
        trades,
        first_purchase,
        cost_basis,
        current_mv,
        snap_rows,
    )

    enriched = dict(position)
    enriched["company_name"] = company_name_for(sym)
    if is_option_instrument_type(inst) and enriched.get("expiry"):
        strike_label = f" ${enriched['strike']}" if enriched.get("strike") is not None else ""
        enriched["display_type"] = f"{'Call' if 'call' in inst else 'Put'}{strike_label} ({enriched['expiry']})"
    else:
        enriched["display_type"] = "Stock" if inst == "stock" else inst.replace("_", " ").title()

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": port_row["name"] if port_row else None,
        "position": enriched,
        "trades": trades,
        "first_purchase": first_purchase,
        "days_held": _days_since(first_purchase),
        "value_history": value_history,
    }
