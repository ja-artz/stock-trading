"""Trade logging and validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from core.db import db_session, row_to_dict
from core.instruments import is_option_instrument_type, normalize_expiry, position_key
from core.portfolio import compute_nav, is_new_position
from core.position_lots import (
    create_lot_from_buy,
    rebuild_position_lots_from_ledger,
    reduce_lot_on_sell,
)
from core.rules import has_blocking_violations, validate_trade
from core import store
from core.snapshots import save_snapshot


def _get_rules_for_portfolio(portfolio_id: int) -> dict:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT s.rules_json FROM portfolios p
            JOIN sessions s ON s.id = p.session_id
            WHERE p.id = ?
            """,
            (portfolio_id,),
        ).fetchone()
        return store.get_portfolio_rules(portfolio_id, row["rules_json"])


def _parse_utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _compute_within_24h(
    portfolio_id: int,
    *,
    plan_item_id: Optional[int] = None,
    weekly_plan_id: Optional[int] = None,
    logged_at: Optional[str] = None,
) -> Optional[bool]:
    """True when trade logged within trade_commit_hours of plan-item acceptance."""
    rules = _get_rules_for_portfolio(portfolio_id)
    commit_hours = float(rules.get("trade_commit_hours", 24))

    anchor: Optional[datetime] = None
    with db_session() as conn:
        if plan_item_id:
            row = conn.execute(
                """
                SELECT d.decided_at FROM decisions d
                WHERE d.plan_item_id = ? AND d.decision = 'accepted'
                ORDER BY d.decided_at DESC LIMIT 1
                """,
                (plan_item_id,),
            ).fetchone()
            if row and row["decided_at"]:
                anchor = _parse_utc(row["decided_at"])
            if weekly_plan_id is None:
                wp = conn.execute(
                    "SELECT weekly_plan_id FROM plan_items WHERE id = ?",
                    (plan_item_id,),
                ).fetchone()
                if wp:
                    weekly_plan_id = int(wp["weekly_plan_id"])

        if anchor is None and weekly_plan_id:
            plan = conn.execute(
                "SELECT plan_at FROM weekly_plans WHERE id = ?",
                (weekly_plan_id,),
            ).fetchone()
            if plan and plan["plan_at"]:
                anchor = _parse_utc(plan["plan_at"])

    if anchor is None:
        return None

    trade_at = _parse_utc(logged_at or store.utc_now_iso())
    return (trade_at - anchor).total_seconds() / 3600.0 <= commit_hours


def log_trade(
    portfolio_id: int,
    *,
    side: str,
    ticker: str,
    instrument_type: str = "stock",
    quantity: float,
    price: float,
    fees: float = 0.0,
    strike: Optional[float] = None,
    expiry: Optional[str] = None,
    plan_item_id: Optional[int] = None,
    member_id: Optional[int] = None,
    note: Optional[str] = None,
    logged_at: Optional[str] = None,
    weekly_plan_id: Optional[int] = None,
    block_on_violations: bool = True,
) -> dict[str, Any]:
    rules_session = _get_rules_for_portfolio(portfolio_id)
    nav_state = compute_nav(portfolio_id)
    new_week = store.count_new_positions_this_week(portfolio_id)
    is_new = is_new_position(
        portfolio_id,
        ticker,
        instrument_type,
        strike=strike,
        expiry=expiry,
    )

    violations = validate_trade(
        rules_session,
        cash_usd=nav_state["cash_usd"],
        nav_usd=nav_state["nav_usd"],
        positions=nav_state["positions"],
        side=side,
        ticker=ticker,
        instrument_type=instrument_type,
        quantity=quantity,
        price=price,
        new_positions_this_week=new_week,
        is_new_position=is_new and side.lower() == "buy",
        portfolio_id=portfolio_id,
        plan_item_id=plan_item_id,
        strike=strike,
        expiry=expiry,
    )

    if block_on_violations and has_blocking_violations(violations):
        return {
            "ok": False,
            "violations": [{"code": v.code, "message": v.message, "severity": v.severity} for v in violations],
        }

    if not plan_item_id:
        from core.plan_linking import infer_plan_item_id_for_trade

        plan_item_id = infer_plan_item_id_for_trade(
            portfolio_id, side=side, ticker=ticker
        )

    if plan_item_id and not weekly_plan_id:
        from core.plan_execution import get_plan_item

        linked = get_plan_item(plan_item_id)
        if linked:
            weekly_plan_id = linked.get("weekly_plan_id")

    executed_within_24h = _compute_within_24h(
        portfolio_id,
        plan_item_id=plan_item_id,
        weekly_plan_id=weekly_plan_id,
        logged_at=logged_at,
    )
    ts = logged_at or store.utc_now_iso()

    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO ledger_events
            (portfolio_id, event_type, side, ticker, instrument_type, quantity, price, fees,
             strike, expiry, plan_item_id, member_id, logged_at, executed_within_24h, note)
            VALUES (?, 'trade', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                portfolio_id,
                side.lower(),
                ticker.upper(),
                instrument_type,
                quantity,
                price,
                fees,
                strike,
                expiry,
                plan_item_id,
                member_id,
                ts,
                1 if executed_within_24h else 0 if executed_within_24h is False else None,
                note,
            ),
        )
        event_id = int(cur.lastrowid)

    side_l = side.lower()
    if side_l == "buy":
        create_lot_from_buy(
            portfolio_id,
            event_id,
            ticker=ticker,
            instrument_type=instrument_type,
            quantity=quantity,
            price=price,
            plan_item_id=plan_item_id,
            strike=strike,
            expiry=expiry,
        )
    elif side_l == "sell":
        reduce_lot_on_sell(
            portfolio_id,
            ticker,
            instrument_type,
            quantity,
            strike=strike,
            expiry=expiry,
        )

    with db_session() as conn:
        port = conn.execute("SELECT session_id FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        session = conn.execute(
            "SELECT household_id FROM sessions WHERE id = ?",
            (port["session_id"],),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO timeline_events (household_id, portfolio_id, event_type, title, detail_json, occurred_at)
            VALUES (?, ?, 'trade', ?, ?, ?)
            """,
            (
                session["household_id"],
                portfolio_id,
                f"{side.upper()} {quantity} {ticker}",
                json.dumps({"ledger_event_id": event_id, "ticker": ticker.upper()}),
                ts,
            ),
        )

    snap = save_snapshot(portfolio_id)
    return {
        "ok": True,
        "ledger_event_id": event_id,
        "violations": [{"code": v.code, "message": v.message, "severity": v.severity} for v in violations],
        "snapshot": snap,
    }


def get_trade(ledger_event_id: int) -> Optional[dict[str, Any]]:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM ledger_events WHERE id = ?",
            (ledger_event_id,),
        ).fetchone()
        if not row:
            return None
        ev = row_to_dict(row)
        if (ev.get("event_type") or "trade").lower() != "trade":
            return None
        return ev


def _ledger_sequence_valid(portfolio_id: int, events: list[dict[str, Any]]) -> Optional[str]:
    """Return error message if replay would leave negative holdings."""
    holdings: dict[str, float] = {}
    for ev in events:
        if (ev.get("event_type") or "trade").lower() != "trade":
            continue
        side = (ev.get("side") or "").lower()
        ticker = (ev.get("ticker") or "").upper()
        inst = ev.get("instrument_type") or "stock"
        key = position_key(
            ticker,
            inst,
            strike=ev.get("strike"),
            expiry=ev.get("expiry"),
        )
        qty = float(ev.get("quantity") or 0)
        if side == "buy":
            holdings[key] = holdings.get(key, 0.0) + qty
        elif side == "sell":
            held = holdings.get(key, 0.0)
            if qty > held + 1e-9:
                return (
                    f"Sell of {qty} {ticker} exceeds available quantity ({held:.4f}) "
                    f"at that point in the ledger"
                )
            holdings[key] = held - qty
    return None


def update_trade(
    ledger_event_id: int,
    *,
    quantity: Optional[float] = None,
    price: Optional[float] = None,
    fees: Optional[float] = None,
    note: Optional[str] = None,
    strike: Optional[float] = None,
    expiry: Optional[str] = None,
    logged_at: Optional[str] = None,
) -> dict[str, Any]:
    """Correct a logged trade (price, fees, quantity, date, note, option contract). Rebuilds lots and NAV."""
    existing = get_trade(ledger_event_id)
    if not existing:
        return {"ok": False, "reason": "Trade not found"}

    portfolio_id = int(existing["portfolio_id"])
    updates: dict[str, Any] = {}

    if quantity is not None:
        if quantity <= 0:
            return {"ok": False, "reason": "quantity must be positive"}
        updates["quantity"] = quantity
    if price is not None:
        if price < 0:
            return {"ok": False, "reason": "price must be non-negative"}
        updates["price"] = price
    if fees is not None:
        if fees < 0:
            return {"ok": False, "reason": "fees must be non-negative"}
        updates["fees"] = fees
    if note is not None:
        updates["note"] = note.strip() or None
    if strike is not None:
        if strike < 0:
            return {"ok": False, "reason": "strike must be non-negative"}
        updates["strike"] = strike
    if expiry is not None:
        updates["expiry"] = normalize_expiry(expiry) if str(expiry).strip() else None
    if logged_at is not None:
        try:
            _parse_utc(logged_at)
        except ValueError:
            return {"ok": False, "reason": "logged_at must be a valid ISO timestamp"}
        updates["logged_at"] = logged_at

    if not updates:
        return {"ok": False, "reason": "No fields to update"}

    merged = {**existing, **updates}
    if is_option_instrument_type(merged.get("instrument_type", "stock")):
        if "strike" in updates or "expiry" in updates:
            if merged.get("strike") is None or not merged.get("expiry"):
                return {"ok": False, "reason": "Options require both strike and expiry"}

    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM ledger_events
            WHERE portfolio_id = ? AND event_type = 'trade'
            ORDER BY logged_at, id
            """,
            (portfolio_id,),
        ).fetchall()
    events = [row_to_dict(r) for r in rows]
    for i, ev in enumerate(events):
        if int(ev["id"]) == ledger_event_id:
            events[i] = merged
            break

    if quantity is not None or logged_at is not None:
        events.sort(key=lambda e: (e.get("logged_at") or "", int(e["id"])))
        seq_err = _ledger_sequence_valid(portfolio_id, events)
        if seq_err:
            return {"ok": False, "reason": seq_err}

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [ledger_event_id]
    with db_session() as conn:
        conn.execute(
            f"UPDATE ledger_events SET {set_clause} WHERE id = ?",
            values,
        )

    rebuild_position_lots_from_ledger(portfolio_id)
    snap = save_snapshot(portfolio_id)
    updated = get_trade(ledger_event_id)
    return {
        "ok": True,
        "ledger_event_id": ledger_event_id,
        "trade": updated,
        "snapshot": snap,
    }


def deposit_cash(
    portfolio_id: int,
    amount_usd: float,
    *,
    note: Optional[str] = None,
    logged_at: Optional[str] = None,
) -> dict[str, Any]:
    """Record external cash added to the Sofi account (increases book cash and NAV)."""
    if amount_usd <= 0:
        return {"ok": False, "reason": "amount_usd must be positive"}

    ts = logged_at or store.utc_now_iso()
    with db_session() as conn:
        port = conn.execute("SELECT session_id FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        if not port:
            return {"ok": False, "reason": f"Portfolio {portfolio_id} not found"}

        cur = conn.execute(
            """
            INSERT INTO ledger_events
            (portfolio_id, event_type, side, ticker, instrument_type, quantity, price, fees,
             logged_at, note)
            VALUES (?, 'cash_deposit', 'in', 'CASH', 'cash', ?, 1, 0, ?, ?)
            """,
            (portfolio_id, amount_usd, ts, note),
        )
        event_id = int(cur.lastrowid)
        session = conn.execute(
            "SELECT household_id FROM sessions WHERE id = ?",
            (port["session_id"],),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO timeline_events (household_id, portfolio_id, event_type, title, detail_json, occurred_at)
            VALUES (?, ?, 'cash_deposit', ?, ?, ?)
            """,
            (
                session["household_id"],
                portfolio_id,
                f"Cash deposit ${amount_usd:.2f}",
                json.dumps({"ledger_event_id": event_id, "amount_usd": amount_usd}),
                ts,
            ),
        )

    snap = save_snapshot(portfolio_id)
    state = compute_nav(portfolio_id)
    return {
        "ok": True,
        "ledger_event_id": event_id,
        "amount_usd": round(amount_usd, 2),
        "cash_usd": state["cash_usd"],
        "nav_usd": state["nav_usd"],
        "snapshot": snap,
    }
