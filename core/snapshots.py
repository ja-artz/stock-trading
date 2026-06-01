"""Portfolio NAV snapshots."""

import json
from typing import Any

from core.db import db_session
from core.portfolio import compute_nav
from core import store


def save_snapshot(portfolio_id: int) -> dict[str, Any]:
    state = compute_nav(portfolio_id)
    as_of = store.utc_now_iso()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (portfolio_id, as_of, cash_usd, positions_json, nav_usd)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                portfolio_id,
                as_of,
                state["cash_usd"],
                json.dumps(state["positions"]),
                state["nav_usd"],
            ),
        )
    return {"portfolio_id": portfolio_id, "as_of": as_of, **state}


def get_latest_snapshot(portfolio_id: int) -> dict | None:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT * FROM snapshots WHERE portfolio_id = ?
            ORDER BY as_of DESC LIMIT 1
            """,
            (portfolio_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "portfolio_id": row["portfolio_id"],
            "as_of": row["as_of"],
            "cash_usd": row["cash_usd"],
            "nav_usd": row["nav_usd"],
            "positions": json.loads(row["positions_json"]),
        }


def get_nav_history(portfolio_id: int, limit: int = 90) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT as_of, nav_usd, cash_usd FROM snapshots
            WHERE portfolio_id = ? ORDER BY as_of DESC LIMIT ?
            """,
            (portfolio_id, limit),
        ).fetchall()
        return [{"as_of": r["as_of"], "nav_usd": r["nav_usd"], "cash_usd": r["cash_usd"]} for r in reversed(rows)]
