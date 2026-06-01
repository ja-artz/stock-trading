"""Reset or import portfolio starting state."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, List, Optional

from core.db import db_session
from core.ledger import log_trade
from core.portfolio import compute_nav
from core.snapshots import save_snapshot
from core import store


def reset_portfolio_to_cash(
    portfolio_id: int,
    cash_usd: float,
    *,
    note: str = "Portfolio reset to cash starting state",
) -> dict[str, Any]:
    """Clear trade history and set book to 100% cash at the given level."""
    if cash_usd < 0:
        raise ValueError("cash_usd must be non-negative")

    with db_session() as conn:
        port = conn.execute("SELECT session_id FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        if not port:
            raise ValueError(f"Portfolio {portfolio_id} not found")

        conn.execute("DELETE FROM ledger_events WHERE portfolio_id = ?", (portfolio_id,))
        conn.execute(
            "UPDATE portfolios SET initial_cash = ? WHERE id = ?",
            (cash_usd, portfolio_id),
        )
        session = conn.execute(
            "SELECT household_id FROM sessions WHERE id = ?",
            (port["session_id"],),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO timeline_events (household_id, portfolio_id, event_type, title, detail_json, occurred_at)
            VALUES (?, ?, 'portfolio_reset', ?, ?, ?)
            """,
            (
                session["household_id"],
                portfolio_id,
                f"Reset to ${cash_usd:.2f} cash",
                json.dumps({"cash_usd": cash_usd}),
                store.utc_now_iso(),
            ),
        )

    snap = save_snapshot(portfolio_id)
    return {"ok": True, "portfolio_id": portfolio_id, "snapshot": snap, "note": note}


def clear_weekly_recommendations(portfolio_id: int) -> int:
    """Delete all weekly plans, items, and decisions for this portfolio."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT id FROM weekly_plans WHERE portfolio_id = ?",
            (portfolio_id,),
        ).fetchall()
        plan_ids = [int(r["id"]) for r in rows]
        for wp_id in plan_ids:
            item_rows = conn.execute(
                "SELECT id FROM plan_items WHERE weekly_plan_id = ?",
                (wp_id,),
            ).fetchall()
            for it in item_rows:
                conn.execute("DELETE FROM decisions WHERE plan_item_id = ?", (it["id"],))
            conn.execute("DELETE FROM plan_items WHERE weekly_plan_id = ?", (wp_id,))
            conn.execute("DELETE FROM weekly_plans WHERE id = ?", (wp_id,))
        return len(plan_ids)


def fresh_start(
    portfolio_id: int,
    cash_usd: float = 1000.0,
) -> dict[str, Any]:
    """Clear weekly recommendations and reset the paper book to cash."""
    cleared = clear_weekly_recommendations(portfolio_id)
    reset = reset_portfolio_to_cash(
        portfolio_id,
        cash_usd,
        note="Fresh start: recommendations cleared and book reset to cash",
    )
    return {**reset, "weekly_plans_cleared": cleared}


def import_starting_state(
    portfolio_id: int,
    cash_usd: float,
    positions: List[dict[str, Any]],
    *,
    clear_existing: bool = True,
) -> dict[str, Any]:
    """
    Set starting book: cash_usd free cash after positions at avg cost.
    initial_cash = cash_usd + sum(qty * avg_cost) so ledger buys reconcile.
    """
    if cash_usd < 0:
        raise ValueError("cash_usd must be non-negative")

    total_cost = 0.0
    normalized = []
    for row in positions:
        ticker = (row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        qty = float(row.get("quantity") or 0)
        avg_cost = float(row.get("avg_cost") or row.get("price") or 0)
        inst = row.get("instrument_type") or "stock"
        if qty <= 0 or avg_cost <= 0:
            continue
        total_cost += qty * avg_cost
        normalized.append(
            {"ticker": ticker, "quantity": qty, "avg_cost": avg_cost, "instrument_type": inst}
        )

    initial_cash = cash_usd + total_cost

    with db_session() as conn:
        port = conn.execute("SELECT session_id FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        if not port:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        if clear_existing:
            conn.execute("DELETE FROM ledger_events WHERE portfolio_id = ?", (portfolio_id,))
        conn.execute(
            "UPDATE portfolios SET initial_cash = ? WHERE id = ?",
            (initial_cash, portfolio_id),
        )

    for row in normalized:
        log_trade(
            portfolio_id,
            side="buy",
            ticker=row["ticker"],
            instrument_type=row["instrument_type"],
            quantity=row["quantity"],
            price=row["avg_cost"],
            note="Imported starting position",
            block_on_violations=False,
        )

    snap = save_snapshot(portfolio_id)
    state = compute_nav(portfolio_id)
    return {
        "ok": True,
        "portfolio_id": portfolio_id,
        "initial_cash_set": initial_cash,
        "cash_after_import": state["cash_usd"],
        "nav_usd": state["nav_usd"],
        "positions_imported": len(normalized),
        "snapshot": snap,
    }


def parse_positions_csv(text: str) -> List[dict[str, Any]]:
    """
    CSV columns (header row required or optional):
    ticker, quantity, avg_cost [, instrument_type]
    """
    reader = csv.DictReader(io.StringIO(text.strip()))
    rows: List[dict[str, Any]] = []
    for line in reader:
        keymap = {k.strip().lower(): v for k, v in line.items() if k}
        ticker = (keymap.get("ticker") or keymap.get("symbol") or "").strip()
        if not ticker:
            continue
        rows.append(
            {
                "ticker": ticker.upper(),
                "quantity": keymap.get("quantity") or keymap.get("qty"),
                "avg_cost": keymap.get("avg_cost") or keymap.get("price") or keymap.get("cost"),
                "instrument_type": keymap.get("instrument_type") or keymap.get("type") or "stock",
            }
        )
    return rows
