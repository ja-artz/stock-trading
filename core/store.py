"""Data access helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Optional

from core.db import db_session, init_db, row_to_dict
from core.plan_sizing import normalize_plan_item_sizing
from core.rules import parse_rules, pacific_week_start
from core.tier_config import (
    normalize_capital_tier,
    normalize_conviction,
    resolve_capital_tier_for_plan_item,
)


def _plan_item_tier_fields(item: dict) -> tuple:
    action = (item.get("action") or "").lower()
    if action in ("watch", "hold"):
        ct = normalize_capital_tier(item.get("capital_tier"))
    else:
        ct = resolve_capital_tier_for_plan_item(item)
    return (
        ct,
        normalize_conviction(item.get("conviction_grade")),
        item.get("sector"),
        item.get("theme_tag"),
        item.get("correlation_group"),
    )


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


def save_portfolio_rules(portfolio_id: int, rules: dict[str, Any]) -> dict:
    merged = parse_rules(rules)
    payload = json.dumps(merged)
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO portfolio_rules (portfolio_id, rules_json)
            VALUES (?, ?)
            ON CONFLICT(portfolio_id) DO UPDATE SET rules_json = excluded.rules_json
            """,
            (portfolio_id, payload),
        )
    return merged


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
        for raw in items:
            item = normalize_plan_item_sizing(dict(raw))
            ct, cg, sec, theme, corr = _plan_item_tier_fields(item)
            conn.execute(
                """
                INSERT INTO plan_items
                (weekly_plan_id, priority, action, ticker, instrument_type, horizon, size_hint,
                 suggested_notional_usd, suggested_quantity, quantity_unit,
                 pct_nav, pct_cash, pct_position, sizing_summary, detail_json,
                 persona_consensus, rationale, rule_warnings,
                 capital_tier, conviction_grade, sector, theme_tag, correlation_group)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    item.get("priority", 1),
                    item.get("action", "watch"),
                    item.get("ticker"),
                    item.get("instrument_type"),
                    item.get("horizon"),
                    item.get("size_hint"),
                    item.get("suggested_notional_usd"),
                    item.get("suggested_quantity"),
                    item.get("quantity_unit"),
                    item.get("pct_nav"),
                    item.get("pct_cash"),
                    item.get("pct_position"),
                    item.get("sizing_summary"),
                    json.dumps(item),
                    json.dumps(item.get("persona_consensus")) if item.get("persona_consensus") else None,
                    item.get("rationale"),
                    json.dumps(item.get("rule_warnings")) if item.get("rule_warnings") else None,
                    ct,
                    cg,
                    sec,
                    theme,
                    corr,
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
                f"Trading plan generated ({len(items)} items)"
                if items
                else "Trading plan generated (no changes)",
                json.dumps({"weekly_plan_id": plan_id, "trigger": trigger_type}),
                utc_now_iso(),
            ),
        )
        return plan_id


def _plan_payload_indicates_no_changes(plan: dict) -> bool:
    payload = plan.get("payload")
    if payload is None and plan.get("payload_json"):
        try:
            payload = json.loads(plan["payload_json"])
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("no_changes") or payload.get("no_trade_week"))


def _prior_plan_items_for_consensus(
    conn, portfolio_id: int, exclude_plan_id: int, limit: int = 80
) -> List[dict]:
    """Recent plan line items from other plans (newest first) for consensus carry-forward."""
    rows = conn.execute(
        """
        SELECT pi.ticker, pi.persona_consensus, pi.action, pi.status, pi.rationale
        FROM plan_items pi
        JOIN weekly_plans wp ON wp.id = pi.weekly_plan_id
        WHERE wp.portfolio_id = ?
          AND pi.weekly_plan_id != ?
          AND pi.ticker IS NOT NULL
          AND TRIM(pi.ticker) != ''
        ORDER BY wp.plan_at DESC, pi.id DESC
        LIMIT ?
        """,
        (portfolio_id, exclude_plan_id, limit),
    ).fetchall()
    out: List[dict] = []
    for row in rows:
        d = row_to_dict(row)
        if d.get("persona_consensus"):
            try:
                d["persona_consensus"] = json.loads(d["persona_consensus"])
            except json.JSONDecodeError:
                d["persona_consensus"] = None
        out.append(d)
    return out


def _hydrate_plan_items(conn, plan_id: int, portfolio_id: int) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM plan_items WHERE weekly_plan_id = ? ORDER BY priority, id",
        (plan_id,),
    ).fetchall()
    plan_items: List[dict] = []
    for it in rows:
        d = row_to_dict(it)
        if d.get("persona_consensus"):
            d["persona_consensus"] = json.loads(d["persona_consensus"])
        if d.get("rule_warnings"):
            d["rule_warnings"] = json.loads(d["rule_warnings"])
        if d.get("detail_json"):
            try:
                detail = json.loads(d["detail_json"])
                if isinstance(detail, dict):
                    d["detail"] = detail
                    if detail.get("thesis_type") and not d.get("thesis_type"):
                        d["thesis_type"] = detail["thesis_type"]
            except json.JSONDecodeError:
                pass
        dec = conn.execute(
            """
            SELECT d.*, m.display_name FROM decisions d
            JOIN members m ON m.id = d.member_id
            WHERE d.plan_item_id = ?
            ORDER BY d.decided_at DESC LIMIT 1
            """,
            (d["id"],),
        ).fetchone()
        d["latest_decision"] = row_to_dict(dec) if dec else None
        led = conn.execute(
            """
            SELECT id, side, ticker, instrument_type, quantity, price, logged_at
            FROM ledger_events WHERE plan_item_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (d["id"],),
        ).fetchone()
        d["auto_trade"] = row_to_dict(led) if led else None
        plan_items.append(d)

    from core.plan_consensus import enrich_plan_items_persona_consensus
    from core.recommendation_execution import attach_execution_status
    from core.ticker_names import enrich_rows_with_company_name

    prior_for_consensus = _prior_plan_items_for_consensus(conn, portfolio_id, plan_id)
    plan_items = enrich_plan_items_persona_consensus(plan_items, prior_for_consensus)
    attach_execution_status(plan_items, portfolio_id)
    return enrich_rows_with_company_name(plan_items)


def _load_weekly_plan_row(conn, row, portfolio_id: int) -> dict:
    plan = row_to_dict(row)
    plan["payload"] = json.loads(plan["payload_json"])
    plan["items"] = _hydrate_plan_items(conn, int(plan["id"]), portfolio_id)
    return plan


def update_weekly_plan_evaluation(
    plan_id: int,
    *,
    portfolio_id: int,
    analysis_run_id: int,
    based_on_analysis_at: str,
    trigger_type: str,
    summary: str,
    payload: dict,
) -> None:
    """Refresh plan metadata on re-evaluation with no new line items (keeps plan_items)."""
    with db_session() as conn:
        conn.execute(
            """
            UPDATE weekly_plans
            SET analysis_run_id = ?, based_on_analysis_at = ?, trigger_type = ?,
                summary = ?, payload_json = ?, plan_at = ?
            WHERE id = ? AND portfolio_id = ?
            """,
            (
                analysis_run_id,
                based_on_analysis_at,
                trigger_type,
                summary,
                json.dumps(payload),
                utc_now_iso(),
                plan_id,
                portfolio_id,
            ),
        )
        port = conn.execute("SELECT session_id FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        session = conn.execute(
            "SELECT household_id FROM sessions WHERE id = ?",
            (port["session_id"],),
        ).fetchone()
        item_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM plan_items WHERE weekly_plan_id = ?",
                (plan_id,),
            ).fetchone()["c"]
            or 0
        )
        conn.execute(
            """
            INSERT INTO timeline_events (household_id, portfolio_id, event_type, title, detail_json, occurred_at)
            VALUES (?, ?, 'weekly_plan', ?, ?, ?)
            """,
            (
                session["household_id"],
                portfolio_id,
                f"Trading plan re-evaluated (no changes, {item_count} open item(s))",
                json.dumps({"weekly_plan_id": plan_id, "trigger": trigger_type, "no_changes": True}),
                utc_now_iso(),
            ),
        )


def get_weekly_plan_by_id(plan_id: int, portfolio_id: int) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM weekly_plans WHERE id = ? AND portfolio_id = ?",
            (plan_id, portfolio_id),
        ).fetchone()
        if not row:
            return None
        return _load_weekly_plan_row(conn, row, portfolio_id)


def _find_prior_plan_with_items(conn, portfolio_id: int, exclude_plan_id: int) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT wp.* FROM weekly_plans wp
        WHERE wp.portfolio_id = ?
          AND wp.id != ?
          AND EXISTS (SELECT 1 FROM plan_items pi WHERE pi.weekly_plan_id = wp.id)
        ORDER BY wp.plan_at DESC
        LIMIT 1
        """,
        (portfolio_id, exclude_plan_id),
    ).fetchone()
    if not row:
        return None
    return _load_weekly_plan_row(conn, row, portfolio_id)


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
        plan = _load_weekly_plan_row(conn, row, portfolio_id)

        if not plan.get("items") and _plan_payload_indicates_no_changes(plan):
            prior = _find_prior_plan_with_items(conn, portfolio_id, int(plan["id"]))
            if prior and prior.get("items"):
                plan["items"] = prior["items"]
                plan["open_items_from_plan_id"] = prior["id"]
        return plan


def get_recent_weekly_plans_context(portfolio_id: int, limit: int = 2) -> List[dict]:
    """Compact prior plans + item decisions for trader-agent prompt (hybrid memory)."""
    with db_session() as conn:
        plans = conn.execute(
            """
            SELECT id, plan_at, summary, trigger_type, based_on_analysis_at
            FROM weekly_plans
            WHERE portfolio_id = ?
            ORDER BY plan_at DESC
            LIMIT ?
            """,
            (portfolio_id, limit),
        ).fetchall()
        out: List[dict] = []
        for p in plans:
            items = conn.execute(
                """
                SELECT id, priority, action, ticker, instrument_type,
                       sizing_summary, size_hint, status, rationale, persona_consensus
                FROM plan_items
                WHERE weekly_plan_id = ?
                ORDER BY priority, id
                """,
                (p["id"],),
            ).fetchall()
            item_rows: List[dict] = []
            for it in items:
                d = row_to_dict(it)
                dec = conn.execute(
                    """
                    SELECT d.decision, d.note, m.display_name AS member, d.decided_at
                    FROM decisions d
                    JOIN members m ON m.id = d.member_id
                    WHERE d.plan_item_id = ?
                    ORDER BY d.decided_at DESC
                    LIMIT 1
                    """,
                    (d["id"],),
                ).fetchone()
                rationale = (d.get("rationale") or "").strip()
                persona_consensus = d.get("persona_consensus")
                if persona_consensus:
                    try:
                        persona_consensus = json.loads(persona_consensus)
                    except json.JSONDecodeError:
                        persona_consensus = None
                item_rows.append(
                    {
                        "priority": d["priority"],
                        "action": d["action"],
                        "ticker": d["ticker"],
                        "instrument_type": d["instrument_type"],
                        "sizing": d.get("sizing_summary") or d.get("size_hint"),
                        "status": d["status"],
                        "rationale_excerpt": rationale[:240] if rationale else None,
                        "persona_consensus": persona_consensus,
                        "latest_decision": row_to_dict(dec) if dec else None,
                    }
                )
            from core.plan_recency import format_minutes_ago, minutes_since

            mins = minutes_since(p["plan_at"])
            out.append(
                {
                    "trading_plan_id": p["id"],
                    "weekly_plan_id": p["id"],
                    "plan_at": p["plan_at"],
                    "minutes_since_plan": round(mins, 1) if mins is not None else None,
                    "plan_ago_label": format_minutes_ago(mins) if mins is not None else None,
                    "trigger": p["trigger_type"],
                    "summary": p["summary"],
                    "based_on_analysis_at": p["based_on_analysis_at"],
                    "items": item_rows,
                }
            )
        return out


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


def get_plan_item(plan_item_id: int, portfolio_id: int) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT pi.* FROM plan_items pi
            JOIN weekly_plans wp ON wp.id = pi.weekly_plan_id
            WHERE pi.id = ? AND wp.portfolio_id = ?
            """,
            (plan_item_id, portfolio_id),
        ).fetchone()
        if not row:
            return None
        items = _hydrate_plan_items(conn, int(row["weekly_plan_id"]), portfolio_id)
        for it in items:
            if int(it["id"]) == plan_item_id:
                return it
        return row_to_dict(row)


def update_plan_item(plan_item_id: int, portfolio_id: int, item: dict) -> None:
    item = normalize_plan_item_sizing(dict(item))
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT pi.id FROM plan_items pi
            JOIN weekly_plans wp ON wp.id = pi.weekly_plan_id
            WHERE pi.id = ? AND wp.portfolio_id = ?
            """,
            (plan_item_id, portfolio_id),
        ).fetchone()
        if not row:
            raise ValueError(f"plan_item {plan_item_id} not found")
        ct, cg, sec, theme, corr = _plan_item_tier_fields(item)
        conn.execute(
            """
            UPDATE plan_items SET
                priority = ?, action = ?, ticker = ?, instrument_type = ?, horizon = ?,
                size_hint = ?, suggested_notional_usd = ?, suggested_quantity = ?,
                quantity_unit = ?, pct_nav = ?, pct_cash = ?, pct_position = ?,
                sizing_summary = ?, detail_json = ?, persona_consensus = ?,
                rationale = ?, rule_warnings = ?,
                capital_tier = ?, conviction_grade = ?, sector = ?, theme_tag = ?,
                correlation_group = ?
            WHERE id = ?
            """,
            (
                item.get("priority", 1),
                item.get("action", "watch"),
                item.get("ticker"),
                item.get("instrument_type"),
                item.get("horizon"),
                item.get("size_hint"),
                item.get("suggested_notional_usd"),
                item.get("suggested_quantity"),
                item.get("quantity_unit"),
                item.get("pct_nav"),
                item.get("pct_cash"),
                item.get("pct_position"),
                item.get("sizing_summary"),
                json.dumps(item),
                json.dumps(item.get("persona_consensus")) if item.get("persona_consensus") else None,
                item.get("rationale"),
                json.dumps(item.get("rule_warnings")) if item.get("rule_warnings") else None,
                ct,
                cg,
                sec,
                theme,
                corr,
                plan_item_id,
            ),
        )


def insert_plan_item(weekly_plan_id: int, portfolio_id: int, item: dict) -> int:
    item = normalize_plan_item_sizing(dict(item))
    with db_session() as conn:
        wp = conn.execute(
            "SELECT id FROM weekly_plans WHERE id = ? AND portfolio_id = ?",
            (weekly_plan_id, portfolio_id),
        ).fetchone()
        if not wp:
            raise ValueError("Trading plan not found")
        max_pri = conn.execute(
            "SELECT COALESCE(MAX(priority), 0) AS m FROM plan_items WHERE weekly_plan_id = ?",
            (weekly_plan_id,),
        ).fetchone()["m"]
        priority = item.get("priority") or int(max_pri) + 1
        ct, cg, sec, theme, corr = _plan_item_tier_fields(item)
        cur = conn.execute(
            """
            INSERT INTO plan_items
            (weekly_plan_id, priority, action, ticker, instrument_type, horizon, size_hint,
             suggested_notional_usd, suggested_quantity, quantity_unit,
             pct_nav, pct_cash, pct_position, sizing_summary, detail_json,
             persona_consensus, rationale, rule_warnings,
             capital_tier, conviction_grade, sector, theme_tag, correlation_group)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                weekly_plan_id,
                priority,
                item.get("action", "watch"),
                item.get("ticker"),
                item.get("instrument_type"),
                item.get("horizon"),
                item.get("size_hint"),
                item.get("suggested_notional_usd"),
                item.get("suggested_quantity"),
                item.get("quantity_unit"),
                item.get("pct_nav"),
                item.get("pct_cash"),
                item.get("pct_position"),
                item.get("sizing_summary"),
                json.dumps(item),
                json.dumps(item.get("persona_consensus")) if item.get("persona_consensus") else None,
                item.get("rationale"),
                json.dumps(item.get("rule_warnings")) if item.get("rule_warnings") else None,
                ct,
                cg,
                sec,
                theme,
                corr,
            ),
        )
        return int(cur.lastrowid)


def supersede_plan_item(plan_item_id: int, portfolio_id: int) -> None:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT pi.id FROM plan_items pi
            JOIN weekly_plans wp ON wp.id = pi.weekly_plan_id
            WHERE pi.id = ? AND wp.portfolio_id = ? AND pi.status = 'pending'
            """,
            (plan_item_id, portfolio_id),
        ).fetchone()
        if not row:
            raise ValueError("Only pending items can be removed")
        conn.execute(
            "UPDATE plan_items SET status = 'superseded' WHERE id = ?",
            (plan_item_id,),
        )


def append_timeline_event(
    household_id: int,
    *,
    portfolio_id: Optional[int],
    event_type: str,
    title: str,
    detail: dict,
) -> None:
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO timeline_events (household_id, portfolio_id, event_type, title, detail_json, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (household_id, portfolio_id, event_type, title, json.dumps(detail), utc_now_iso()),
        )


def create_chat_thread(
    household_id: int,
    portfolio_id: int,
    *,
    weekly_plan_id: Optional[int] = None,
    title: Optional[str] = None,
    focus: Optional[dict] = None,
) -> int:
    now = utc_now_iso()
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_chat_threads
            (household_id, portfolio_id, weekly_plan_id, title, focus_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                household_id,
                portfolio_id,
                weekly_plan_id,
                title,
                json.dumps(focus) if focus else None,
                now,
                now,
            ),
        )
        return int(cur.lastrowid)


def list_chat_threads(portfolio_id: int, limit: int = 20) -> List[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM agent_chat_threads
            WHERE portfolio_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (portfolio_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = row_to_dict(r)
            if d.get("focus_json"):
                d["focus"] = json.loads(d["focus_json"])
            out.append(d)
        return out


def get_chat_thread(thread_id: int, portfolio_id: int) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM agent_chat_threads WHERE id = ? AND portfolio_id = ?",
            (thread_id, portfolio_id),
        ).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        if d.get("focus_json"):
            d["focus"] = json.loads(d["focus_json"])
        return d


def update_chat_thread_focus(thread_id: int, portfolio_id: int, focus: dict) -> None:
    with db_session() as conn:
        conn.execute(
            """
            UPDATE agent_chat_threads
            SET focus_json = ?, updated_at = ?
            WHERE id = ? AND portfolio_id = ?
            """,
            (json.dumps(focus), utc_now_iso(), thread_id, portfolio_id),
        )


def touch_chat_thread(thread_id: int) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE agent_chat_threads SET updated_at = ? WHERE id = ?",
            (utc_now_iso(), thread_id),
        )


def add_chat_message(
    thread_id: int,
    role: str,
    content: str,
    metadata: Optional[dict] = None,
) -> int:
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_chat_messages (thread_id, role, content, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (thread_id, role, content, json.dumps(metadata) if metadata else None, utc_now_iso()),
        )
        conn.execute(
            "UPDATE agent_chat_threads SET updated_at = ? WHERE id = ?",
            (utc_now_iso(), thread_id),
        )
        return int(cur.lastrowid)


def get_chat_messages(thread_id: int, limit: int = 100) -> List[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM agent_chat_messages
            WHERE thread_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (thread_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = row_to_dict(r)
            if d.get("metadata_json"):
                d["metadata"] = json.loads(d["metadata_json"])
            out.append(d)
        return out


def save_plan_revision_proposal(
    *,
    thread_id: Optional[int],
    weekly_plan_id: int,
    portfolio_id: int,
    revision: dict,
    preview: dict,
    status: str = "pending",
) -> int:
    now = utc_now_iso()
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO plan_revision_proposals
            (thread_id, weekly_plan_id, portfolio_id, revision_json, preview_json, status, created_at, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                weekly_plan_id,
                portfolio_id,
                json.dumps(revision),
                json.dumps(preview),
                status,
                now,
                now if status == "applied" else None,
            ),
        )
        return int(cur.lastrowid)


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
