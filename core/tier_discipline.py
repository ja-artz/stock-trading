"""Daily discipline: action items from tier exit rules."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, List, Optional

from core.db import db_session, row_to_dict
from core import store
from core.position_lots import enrich_lots_with_marks, get_open_lots
from core.portfolio import compute_nav
from core.rules import parse_rules
from core.tier_engine import (
    ActionItemDraft,
    build_tier_state,
    evaluate_position_exits,
)
from core.tier_config import (
    PROFIT_RECYCLING,
    get_tier_catalog,
    tier_display_name,
    tier_hint,
)


PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _rules_for_portfolio(portfolio_id: int) -> dict:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT s.rules_json FROM portfolios p
            JOIN sessions s ON s.id = p.session_id
            WHERE p.id = ?
            """,
            (portfolio_id,),
        ).fetchone()
        return store.get_portfolio_rules(portfolio_id, row["rules_json"] if row else None)


def _sort_items(items: List[ActionItemDraft]) -> List[ActionItemDraft]:
    return sorted(items, key=lambda i: PRIORITY_ORDER.get(i.priority, 9))


def run_daily_discipline(
    portfolio_id: int,
    as_of: Optional[date] = None,
) -> List[dict[str, Any]]:
    """Generate idempotent action items for the given date."""
    today = as_of or date.today()
    generated_at = store.utc_now_iso()
    rules = _rules_for_portfolio(portfolio_id)
    lots = enrich_lots_with_marks(portfolio_id, get_open_lots(portfolio_id))

    from core.position_lots import count_tier1_opens_this_month

    nav = compute_nav(portfolio_id)
    state = build_tier_state(
        nav_usd=nav["nav_usd"],
        cash_usd=nav["cash_usd"],
        lots=lots,
        rules=rules,
        tier_1_trades_this_month=count_tier1_opens_this_month(portfolio_id),
    )

    drafts: List[ActionItemDraft] = []
    for lot in lots:
        mark = float(lot.get("mark_price") or lot.get("entry_price") or 0)
        drafts.extend(evaluate_position_exits(lot, mark_price=mark, as_of=today))

    for tier in state.over_capacity_tiers:
        drafts.append(
            ActionItemDraft(
                position_lot_id=None,
                plan_item_id=None,
                ticker="PORTFOLIO",
                priority="medium",
                action="tier_capacity_review",
                reason_code=f"tier_{tier}_over_max_positions",
                detail={"capital_tier": tier, "position_count": state.buckets[tier].position_count},
            )
        )

    drafts = _sort_items(drafts)
    saved: List[dict[str, Any]] = []
    day_key = today.isoformat()

    with db_session() as conn:
        for d in drafts:
            dup = None
            if d.position_lot_id:
                dup = conn.execute(
                    """
                    SELECT id FROM action_items
                    WHERE portfolio_id = ? AND position_lot_id = ? AND reason_code = ?
                      AND status IN ('open', 'acknowledged')
                      AND date(generated_at) = date(?)
                    """,
                    (portfolio_id, d.position_lot_id, d.reason_code, day_key),
                ).fetchone()
            if dup:
                continue

            detail = dict(d.detail)
            detail.setdefault("ticker", d.ticker)

            cur = conn.execute(
                """
                INSERT INTO action_items
                (portfolio_id, position_lot_id, plan_item_id, generated_at,
                 priority, action, reason_code, detail_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    portfolio_id,
                    d.position_lot_id,
                    d.plan_item_id,
                    generated_at,
                    d.priority,
                    d.action,
                    d.reason_code,
                    json.dumps(detail),
                ),
            )
            row = conn.execute(
                "SELECT * FROM action_items WHERE id = ?",
                (int(cur.lastrowid),),
            ).fetchone()
            if row:
                item = _action_item_dict(row)
                saved.append(item)
                _maybe_record_profit_recycling(conn, portfolio_id, d, item)

    return saved


def _maybe_record_profit_recycling(
    conn: Any,
    portfolio_id: int,
    draft: ActionItemDraft,
    saved_item: dict[str, Any],
) -> None:
    recycling = draft.detail.get("profit_recycling")
    if not recycling or not draft.position_lot_id:
        return
    lot = conn.execute(
        """
        SELECT quantity_remaining, entry_price, capital_tier FROM position_lots WHERE id = ?
        """,
        (draft.position_lot_id,),
    ).fetchone()
    if not lot:
        return
    pl_pct = float(draft.detail.get("pl_pct") or 0)
    if pl_pct <= 0:
        return
    mv = float(lot["quantity_remaining"]) * float(lot["entry_price"]) * (pl_pct / 100.0)
    source_tier = int(lot["capital_tier"])
    for entry in recycling:
        dest = int(entry.get("dest_tier", entry[0] if isinstance(entry, tuple) else 0))
        frac = float(entry.get("fraction", entry[1] if isinstance(entry, tuple) else 0))
        conn.execute(
            """
            INSERT INTO tier_transfer_suggestions
            (portfolio_id, source_tier, dest_tier, amount_usd, reason_code, action_item_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                portfolio_id,
                source_tier,
                dest,
                round(mv * frac, 2),
                f"profit_recycling_{draft.reason_code}",
                saved_item.get("id"),
            ),
        )


def list_action_items(
    portfolio_id: int,
    *,
    status: Optional[str] = None,
    include_today_only: bool = False,
) -> List[dict[str, Any]]:
    with db_session() as conn:
        q = "SELECT * FROM action_items WHERE portfolio_id = ?"
        params: list = [portfolio_id]
        if status:
            q += " AND status = ?"
            params.append(status)
        if include_today_only:
            q += " AND date(generated_at) = date('now')"
        q += " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, generated_at DESC"
        rows = conn.execute(q, params).fetchall()
    return [_action_item_dict(r) for r in rows]


def update_action_item_status(
    action_item_id: int,
    portfolio_id: int,
    status: str,
    *,
    override_note: Optional[str] = None,
) -> dict[str, Any]:
    allowed = ("acknowledged", "executed", "overridden", "open")
    if status not in allowed:
        raise ValueError(f"Invalid status: {status}")
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM action_items WHERE id = ? AND portfolio_id = ?",
            (action_item_id, portfolio_id),
        ).fetchone()
        if not row:
            raise ValueError("Action item not found")
        overridden_at = store.utc_now_iso() if status == "overridden" else None
        conn.execute(
            """
            UPDATE action_items SET status = ?, overridden_at = ?, override_note = ?
            WHERE id = ?
            """,
            (status, overridden_at, override_note, action_item_id),
        )
        if status == "executed" and row["position_lot_id"]:
            from core.position_lots import record_partial_exit

            record_partial_exit(int(row["position_lot_id"]), row["reason_code"])
        updated = conn.execute(
            "SELECT * FROM action_items WHERE id = ?",
            (action_item_id,),
        ).fetchone()
    return _action_item_dict(updated)


def get_discipline_summary(portfolio_id: int) -> dict[str, Any]:
    from core.position_lots import count_tier1_opens_this_month, get_unmapped_positions

    rules = _rules_for_portfolio(portfolio_id)
    nav = compute_nav(portfolio_id)
    lots = enrich_lots_with_marks(portfolio_id, get_open_lots(portfolio_id))
    state = build_tier_state(
        nav_usd=nav["nav_usd"],
        cash_usd=nav["cash_usd"],
        lots=lots,
        rules=rules,
        tier_1_trades_this_month=count_tier1_opens_this_month(portfolio_id),
    )
    items = list_action_items(portfolio_id, status="open")
    return {
        "tier_catalog": get_tier_catalog(rules),
        "tier_state": {
            str(t): {
                "id": t,
                "name": tier_display_name(t),
                "hint": tier_hint(t),
                "budget_usd": b.budget_usd,
                "deployed_usd": round(b.deployed_usd, 2),
                "available_usd": round(b.available_usd, 2),
                "position_count": b.position_count,
                "max_positions": b.max_positions,
            }
            for t, b in state.buckets.items()
            if t <= 3
        },
        "open_action_items": items,
        "unmapped_positions": get_unmapped_positions(portfolio_id),
        "over_capacity_tiers": state.over_capacity_tiers,
    }


def _action_item_dict(row: Any) -> dict[str, Any]:
    d = row_to_dict(row) or {}
    if d.get("detail_json") and isinstance(d["detail_json"], str):
        try:
            d["detail"] = json.loads(d["detail_json"])
        except json.JSONDecodeError:
            d["detail"] = {}
    return d
