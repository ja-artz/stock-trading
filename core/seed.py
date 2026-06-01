"""Seed default household if empty."""

import json
import os
from datetime import datetime, timezone

import config
from core.db import db_session, init_db
from core.rules import DEFAULT_RULES
from core.snapshots import save_snapshot


def ensure_seeded() -> None:
    init_db()
    with db_session() as conn:
        existing = conn.execute("SELECT id FROM households LIMIT 1").fetchone()
        if existing:
            return

        household_name = config.HOUSEHOLD_NAME
        member1 = config.MEMBER_1_NAME
        member2 = config.MEMBER_2_NAME
        initial_cash = config.INITIAL_CASH
        started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        cur = conn.execute(
            "INSERT INTO households (name, timezone) VALUES (?, ?)",
            (household_name, "America/Los_Angeles"),
        )
        household_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO members (household_id, display_name) VALUES (?, ?)",
            (household_id, member1),
        )
        conn.execute(
            "INSERT INTO members (household_id, display_name) VALUES (?, ?)",
            (household_id, member2),
        )
        cur = conn.execute(
            """
            INSERT INTO sessions (household_id, name, started_at, rules_json, status)
            VALUES (?, ?, ?, ?, 'active')
            """,
            (household_id, "Trading session", started, json.dumps(DEFAULT_RULES)),
        )
        session_id = int(cur.lastrowid)
        cur = conn.execute(
            """
            INSERT INTO portfolios (session_id, name, initial_cash, is_active)
            VALUES (?, ?, ?, 1)
            """,
            (session_id, "Household", initial_cash),
        )
        portfolio_id = int(cur.lastrowid)

    save_snapshot(portfolio_id)
