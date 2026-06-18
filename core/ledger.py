"""Trade logging and validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from core.db import db_session
from core.portfolio import compute_nav, is_new_position
from core.position_lots import create_lot_from_buy, reduce_lot_on_sell
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
    is_new = is_new_position(portfolio_id, ticker)

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
            expiry=expiry,
        )
    elif side_l == "sell":
        reduce_lot_on_sell(portfolio_id, ticker, instrument_type, quantity)

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
