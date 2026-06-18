"""Link manual ledger trades to accepted plan items and persona consensus."""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from core.db import db_session, row_to_dict
from core.plan_consensus import normalize_persona_consensus
from core.tier_config import resolve_capital_tier_for_plan_item


def accepted_plans_by_ticker(
    portfolio_id: int,
    *,
    actions: Optional[Tuple[str, ...]] = None,
) -> Dict[str, dict]:
    """Most recent accepted plan item per ticker (newest acceptance first)."""
    params: list = [portfolio_id]
    action_filter = ""
    if actions:
        placeholders = ",".join("?" * len(actions))
        action_filter = f" AND LOWER(pi.action) IN ({placeholders})"
        params.extend(a.lower() for a in actions)

    with db_session() as conn:
        rows = conn.execute(
            f"""
            SELECT pi.id, pi.ticker, pi.action, pi.horizon, pi.capital_tier,
                   pi.persona_consensus, d.decided_at
            FROM plan_items pi
            JOIN weekly_plans wp ON wp.id = pi.weekly_plan_id
            JOIN decisions d ON d.plan_item_id = pi.id AND d.decision = 'accepted'
            WHERE wp.portfolio_id = ?{action_filter}
            ORDER BY d.decided_at DESC
            """,
            params,
        ).fetchall()

    out: Dict[str, dict] = {}
    for row in rows:
        d = row_to_dict(row) or {}
        ticker = (d.get("ticker") or "").upper()
        if not ticker or ticker in out:
            continue
        raw = d.get("persona_consensus")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = None
        out[ticker] = {
            "plan_item_id": int(d["id"]),
            "action": d.get("action"),
            "horizon": d.get("horizon"),
            "capital_tier": resolve_capital_tier_for_plan_item(d),
            "persona_consensus": normalize_persona_consensus(raw),
            "decided_at": d.get("decided_at"),
        }
    return out


def infer_plan_item_id_for_trade(
    portfolio_id: int,
    *,
    side: str,
    ticker: str,
) -> Optional[int]:
    """Best-effort link for manual Sofi logs without an explicit plan_item_id."""
    side_l = (side or "").lower()
    ticker_u = (ticker or "").upper()
    if not ticker_u:
        return None
    if side_l == "buy":
        plans = accepted_plans_by_ticker(portfolio_id, actions=("buy", "hedge"))
    elif side_l == "sell":
        plans = accepted_plans_by_ticker(portfolio_id, actions=("sell", "trim"))
    else:
        return None
    match = plans.get(ticker_u)
    return int(match["plan_item_id"]) if match else None


def resolve_trade_attribution(
    portfolio_id: int,
    ticker: str,
    *,
    buy_plan_item_id: Optional[int] = None,
    sell_plan_item_id: Optional[int] = None,
    plan_meta: Optional[Dict[int, dict]] = None,
    entry_plans: Optional[Dict[str, dict]] = None,
    any_plans: Optional[Dict[str, dict]] = None,
) -> dict:
    """Attach persona consensus to a closed or open trade."""
    from core.insights_analytics import _load_plan_item_meta
    from core.plan_consensus import personas_matching_stance

    ticker_u = ticker.upper()
    entry_plans = entry_plans or accepted_plans_by_ticker(
        portfolio_id, actions=("buy", "hedge")
    )
    any_plans = any_plans or accepted_plans_by_ticker(portfolio_id)

    if plan_meta is None:
        ids: List[int] = []
        for pid in (buy_plan_item_id, sell_plan_item_id):
            if pid:
                ids.append(int(pid))
        for bucket in (entry_plans, any_plans):
            ids.extend(int(p["plan_item_id"]) for p in bucket.values())
        plan_meta = _load_plan_item_meta(list(set(ids)))

    consensus = None
    plan_item_id: Optional[int] = None
    attribution: Optional[str] = None

    for pid in (buy_plan_item_id, sell_plan_item_id):
        if not pid:
            continue
        info = plan_meta.get(int(pid))
        if info and info.get("persona_consensus"):
            consensus = info["persona_consensus"]
            plan_item_id = int(pid)
            attribution = "ledger"
            break

    if not consensus:
        entry = entry_plans.get(ticker_u)
        if entry and entry.get("persona_consensus"):
            consensus = entry["persona_consensus"]
            plan_item_id = entry["plan_item_id"]
            attribution = "accepted_entry"
        else:
            any_plan = any_plans.get(ticker_u)
            if any_plan and any_plan.get("persona_consensus"):
                consensus = any_plan["persona_consensus"]
                plan_item_id = any_plan["plan_item_id"]
                attribution = "accepted_any"

    matched = personas_matching_stance(consensus)
    return {
        "plan_item_id": plan_item_id,
        "persona_consensus": consensus,
        "matched_personas": matched,
        "followed_rec": attribution is not None,
        "attribution": attribution,
    }
