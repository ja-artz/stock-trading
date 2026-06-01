"""Trade logging and validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from core.db import db_session
from core.portfolio import compute_nav, is_new_position
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


def _compute_within_24h(weekly_plan_id: Optional[int], logged_at: Optional[str]) -> Optional[bool]:
    if not weekly_plan_id:
        return None
    with db_session() as conn:
        plan = conn.execute(
            "SELECT plan_at FROM weekly_plans WHERE id = ?",
            (weekly_plan_id,),
        ).fetchone()
        if not plan:
            return None
        plan_at = datetime.fromisoformat(plan["plan_at"].replace("Z", "+00:00"))
        trade_at = datetime.fromisoformat((logged_at or store.utc_now_iso()).replace("Z", "+00:00"))
        if plan_at.tzinfo is None:
            plan_at = plan_at.replace(tzinfo=timezone.utc)
        if trade_at.tzinfo is None:
            trade_at = trade_at.replace(tzinfo=timezone.utc)
        return (trade_at - plan_at).total_seconds() / 3600.0 <= 24.0


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
    )

    if block_on_violations and has_blocking_violations(violations):
        return {
            "ok": False,
            "violations": [{"code": v.code, "message": v.message, "severity": v.severity} for v in violations],
        }

    executed_within_24h = _compute_within_24h(weekly_plan_id, logged_at)
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
