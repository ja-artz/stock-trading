"""Data access helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Optional

from core.db import db_session, init_db, row_to_dict
from core.rules import parse_rules, pacific_week_start


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_database() -> None:
    init_db()


def get_household(household_id: int = 1) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM households WHERE id = ?", (household_id,)).fetchone()
        return row_to_dict(row)


def get_members(household_id: int = 1) -> List[dict]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM members WHERE household_id = ? ORDER BY id",
            (household_id,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def get_active_session(household_id: int = 1) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT * FROM sessions
            WHERE household_id = ? AND status = 'active'
            ORDER BY id DESC LIMIT 1
            """,
            (household_id,),
        ).fetchone()
        return row_to_dict(row)


def get_portfolios(session_id: int, active_only: bool = True) -> List[dict]:
    with db_session() as conn:
        q = "SELECT * FROM portfolios WHERE session_id = ?"
        if active_only:
            q += " AND is_active = 1"
        q += " ORDER BY id"
        rows = conn.execute(q, (session_id,)).fetchall()
        return [row_to_dict(r) for r in rows]


def get_portfolio_rules(portfolio_id: int, session_rules_json: str) -> dict:
    with db_session() as conn:
        row = conn.execute(
            "SELECT rules_json FROM portfolio_rules WHERE portfolio_id = ?",
            (portfolio_id,),
        ).fetchone()
        if row:
            return parse_rules(row["rules_json"])
        return parse_rules(session_rules_json)


def create_analysis_run(
    household_id: int,
    payload: list,
    run_type: str = "daily",
    export_path: Optional[str] = None,
) -> int:
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO analysis_runs (household_id, run_at, run_type, status, payload_json, export_path)
            VALUES (?, ?, ?, 'completed', ?, ?)
            """,
            (household_id, utc_now_iso(), run_type, json.dumps(payload), export_path),
        )
        run_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO timeline_events (household_id, event_type, title, detail_json, occurred_at)
            VALUES (?, 'analysis_run', ?, ?, ?)
            """,
            (
                household_id,
                f"Daily analysis completed ({len(payload)} stories)",
                json.dumps({"analysis_run_id": run_id, "run_type": run_type}),
                utc_now_iso(),
            ),
        )
        return int(run_id)


def get_latest_analysis_run(household_id: int = 1) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT * FROM analysis_runs
            WHERE household_id = ? AND status = 'completed'
            ORDER BY run_at DESC LIMIT 1
            """,
            (household_id,),
        ).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        if d.get("payload_json"):
            d["payload"] = json.loads(d["payload_json"])
        return d


def get_analysis_run(run_id: int) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        if d.get("payload_json"):
            d["payload"] = json.loads(d["payload_json"])
        return d


def create_weekly_plan(
    portfolio_id: int,
    analysis_run_id: int,
    based_on_analysis_at: str,
    trigger_type: str,
    summary: str,
    payload: dict,
    items: List[dict],
) -> int:
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO weekly_plans
            (portfolio_id, analysis_run_id, plan_at, based_on_analysis_at, trigger_type, summary, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                portfolio_id,
                analysis_run_id,
                utc_now_iso(),
                based_on_analysis_at,
                trigger_type,
                summary,
                json.dumps(payload),
            ),
        )
        plan_id = int(cur.lastrowid)
        for item in items:
            conn.execute(
                """
                INSERT INTO plan_items
                (weekly_plan_id, priority, action, ticker, instrument_type, horizon, size_hint,
                 persona_consensus, rationale, rule_warnings)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    item.get("priority", 1),
                    item.get("action", "watch"),
                    item.get("ticker"),
                    item.get("instrument_type"),
                    item.get("horizon"),
                    item.get("size_hint"),
                    json.dumps(item.get("persona_consensus")) if item.get("persona_consensus") else None,
                    item.get("rationale"),
                    json.dumps(item.get("rule_warnings")) if item.get("rule_warnings") else None,
                ),
            )
        port = conn.execute("SELECT session_id FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        session = conn.execute(
            "SELECT household_id FROM sessions WHERE id = ?",
            (port["session_id"],),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO timeline_events (household_id, portfolio_id, event_type, title, detail_json, occurred_at)
            VALUES (?, ?, 'weekly_plan', ?, ?, ?)
            """,
            (
                session["household_id"],
                portfolio_id,
                f"Weekly plan generated ({len(items)} items)",
                json.dumps({"weekly_plan_id": plan_id, "trigger": trigger_type}),
                utc_now_iso(),
            ),
        )
        return plan_id


def get_current_weekly_plan(portfolio_id: int) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT * FROM weekly_plans WHERE portfolio_id = ?
            ORDER BY plan_at DESC LIMIT 1
            """,
            (portfolio_id,),
        ).fetchone()
        if not row:
            return None
        plan = row_to_dict(row)
        plan["payload"] = json.loads(plan["payload_json"])
        items = conn.execute(
            "SELECT * FROM plan_items WHERE weekly_plan_id = ? ORDER BY priority, id",
            (plan["id"],),
        ).fetchall()
        plan_items = []
        for it in items:
            d = row_to_dict(it)
            if d.get("persona_consensus"):
                d["persona_consensus"] = json.loads(d["persona_consensus"])
            if d.get("rule_warnings"):
                d["rule_warnings"] = json.loads(d["rule_warnings"])
            dec = conn.execute(
                """
                SELECT d.*, m.display_name FROM decisions d
                JOIN members m ON m.id = d.member_id
                WHERE d.plan_item_id = ?
                ORDER BY d.decided_at DESC LIMIT 1
                """,
                (d["id"],),
            ).fetchone()
            d["latest_decision"] = row_to_dict(dec)
            plan_items.append(d)
        plan["items"] = plan_items
        return plan


def record_decision(plan_item_id: int, member_id: int, decision: str, note: Optional[str] = None) -> int:
    with db_session() as conn:
        conn.execute(
            "UPDATE plan_items SET status = ? WHERE id = ?",
            (decision if decision in ("accepted", "rejected", "deferred") else "pending", plan_item_id),
        )
        cur = conn.execute(
            """
            INSERT INTO decisions (plan_item_id, member_id, decision, note, decided_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (plan_item_id, member_id, decision, note, utc_now_iso()),
        )
        return int(cur.lastrowid)


def add_portfolio(session_id: int, name: str, initial_cash: float) -> int:
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO portfolios (session_id, name, initial_cash, is_active)
            VALUES (?, ?, ?, 1)
            """,
            (session_id, name, initial_cash),
        )
        return int(cur.lastrowid)


def get_timeline(household_id: int = 1, limit: int = 50) -> List[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM timeline_events
            WHERE household_id = ?
            ORDER BY occurred_at DESC LIMIT ?
            """,
            (household_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = row_to_dict(r)
            if d.get("detail_json"):
                d["detail"] = json.loads(d["detail_json"])
            out.append(d)
        return out


def save_insight_report(
    household_id: int,
    payload: dict,
    portfolio_id: Optional[int] = None,
    report_type: str = "lessons",
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
) -> int:
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO insight_reports
            (household_id, portfolio_id, report_type, period_start, period_end, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                household_id,
                portfolio_id,
                report_type,
                period_start,
                period_end,
                json.dumps(payload),
            ),
        )
        return int(cur.lastrowid)


def get_latest_insight(household_id: int = 1, portfolio_id: Optional[int] = None) -> Optional[dict]:
    with db_session() as conn:
        if portfolio_id:
            row = conn.execute(
                """
                SELECT * FROM insight_reports
                WHERE household_id = ? AND (portfolio_id = ? OR portfolio_id IS NULL)
                ORDER BY created_at DESC LIMIT 1
                """,
                (household_id, portfolio_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM insight_reports WHERE household_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (household_id,),
            ).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        d["payload"] = json.loads(d["payload_json"])
        return d


def count_new_positions_this_week(portfolio_id: int) -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    week_start = pacific_week_start(datetime.now(ZoneInfo("America/Los_Angeles")))
    week_start_iso = week_start.isoformat()
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT ticker, MIN(logged_at) AS first_buy
            FROM ledger_events
            WHERE portfolio_id = ? AND side = 'buy'
            GROUP BY ticker
            """,
            (portfolio_id,),
        ).fetchall()
        count = 0
        for r in rows:
            if r["first_buy"] >= week_start_iso:
                count += 1
        return count
