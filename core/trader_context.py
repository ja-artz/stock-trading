"""Shared context assembly for trader agent plan generation and chat."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from core.market_quotes import (
    collect_symbols_for_quotes,
    fetch_market_quotes,
    fetch_option_quotes,
    format_option_quotes_for_prompt,
    format_quotes_for_prompt,
    merge_position_marks,
)
from core.plan_recency import last_plan_timing_block
from core.portfolio import compute_nav, open_option_count
from core import store


def _trim_story(story: dict, *, full: bool = False) -> dict:
    """Compact story envelope for chat; full=True keeps analyst payloads."""
    if full:
        return story
    profiles = story.get("analyst_profiles") or {}
    compact_profiles: dict[str, Any] = {}
    for pid, prof in profiles.items():
        if not isinstance(prof, dict):
            continue
        recs = prof.get("recommendations") or []
        compact_profiles[pid] = {
            "thesis": (prof.get("thesis") or "")[:500],
            "risk_level": prof.get("risk_level"),
            "recommended_tier": prof.get("recommended_tier"),
            "recommendations": [
                {
                    "ticker": r.get("ticker"),
                    "instrument_type": r.get("instrument_type"),
                    "rationale": (r.get("rationale") or "")[:200],
                }
                for r in recs[:5]
                if isinstance(r, dict)
            ],
        }
    indirect = story.get("indirect_effects")
    compact_indirect = None
    if isinstance(indirect, dict) and indirect.get("enabled"):
        chains = indirect.get("causal_chains") or []
        compact_indirect = {
            "enabled": True,
            "causal_chains": [
                {
                    "thesis_one_liner": c.get("thesis_one_liner"),
                    "time_horizon": c.get("time_horizon"),
                    "tickers": c.get("tickers"),
                }
                for c in chains[:3]
                if isinstance(c, dict)
            ],
        }
    return {
        "article_title": story.get("article_title"),
        "article_link": story.get("article_link"),
        "article_published": story.get("article_published"),
        "shared_context": story.get("shared_context"),
        "indirect_effects": compact_indirect,
        "analyst_profiles": compact_profiles,
    }


def _compact_plan_item(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "priority": item.get("priority"),
        "thesis_type": item.get("thesis_type") or (item.get("detail") or {}).get("thesis_type"),
        "action": item.get("action"),
        "ticker": item.get("ticker"),
        "instrument_type": item.get("instrument_type"),
        "horizon": item.get("horizon"),
        "sizing_summary": item.get("sizing_summary"),
        "suggested_notional_usd": item.get("suggested_notional_usd"),
        "suggested_quantity": item.get("suggested_quantity"),
        "quantity_unit": item.get("quantity_unit"),
        "pct_nav": item.get("pct_nav"),
        "pct_cash": item.get("pct_cash"),
        "pct_position": item.get("pct_position"),
        "status": item.get("status"),
        "rationale": item.get("rationale"),
        "rule_warnings": item.get("rule_warnings"),
        "latest_decision": item.get("latest_decision"),
        "persona_consensus": item.get("persona_consensus"),
        "persona_consensus_carried_forward": item.get("persona_consensus_carried_forward"),
        "capital_tier": item.get("capital_tier"),
        "conviction_grade": item.get("conviction_grade"),
        "sector": item.get("sector"),
        "theme_tag": item.get("theme_tag"),
    }


def _compact_plan(plan: Optional[dict]) -> Optional[dict]:
    if not plan:
        return None
    payload = plan.get("payload") or {}
    return {
        "id": plan.get("id"),
        "weekly_plan_id": plan.get("id"),
        "summary": plan.get("summary") or payload.get("summary"),
        "plan_at": plan.get("plan_at"),
        "based_on_analysis_at": plan.get("based_on_analysis_at"),
        "no_changes": bool(payload.get("no_changes") or payload.get("no_trade_week")),
        "items": [_compact_plan_item(i) for i in plan.get("items") or []],
    }


def build_trader_context(
    portfolio_id: int,
    *,
    weekly_plan_id: Optional[int] = None,
    analysis_run_id: Optional[int] = None,
    history_depth: int = 2,
    focus: Optional[dict] = None,
    include_full_analysis: bool = False,
    fetch_quotes: bool = True,
) -> dict[str, Any]:
    """
    Build a JSON-serializable context bundle for trader plan generation or chat.

    focus examples:
      {"type": "plan_item", "plan_item_id": 12}
      {"type": "story", "run_id": 1, "story_index": 0}
    """
    session = store.get_active_session()
    if not session:
        raise RuntimeError("No active session. Run scripts/seed_household.py first.")

    household_id = int(session["household_id"])
    run = (
        store.get_analysis_run(analysis_run_id)
        if analysis_run_id
        else store.get_latest_analysis_run(household_id)
    )
    if not run:
        raise RuntimeError("No analysis run available. Run daily analysis first.")

    stories: List[dict] = run.get("payload") or []
    rules = store.get_portfolio_rules(portfolio_id, session["rules_json"])
    nav_state = compute_nav(portfolio_id)
    new_pos_week = store.count_new_positions_this_week(portfolio_id)

    if weekly_plan_id:
        current_plan = store.get_weekly_plan_by_id(weekly_plan_id, portfolio_id)
    else:
        current_plan = store.get_current_weekly_plan(portfolio_id)

    timing = last_plan_timing_block(
        plan_at=current_plan.get("plan_at") if current_plan else None,
        based_on_analysis_at=current_plan.get("based_on_analysis_at") if current_plan else None,
        current_analysis_at=run["run_at"],
        current_analysis_run_id=int(run["id"]),
        last_analysis_run_id=int(current_plan["analysis_run_id"])
        if current_plan and current_plan.get("analysis_run_id")
        else None,
    )

    recent_plans = store.get_recent_weekly_plans_context(portfolio_id, limit=history_depth)

    quote_bundle: dict[str, Any] = {"quotes": {}, "fetched_at": None}
    option_quote_bundle: dict[str, Any] = {"contracts": [], "as_of": None}
    if fetch_quotes:
        symbols = set(collect_symbols_for_quotes(stories, nav_state.get("positions")))
        if current_plan:
            for it in current_plan.get("items") or []:
                t = (it.get("ticker") or "").strip().upper()
                if t:
                    symbols.add(t)
        quote_bundle = fetch_market_quotes(sorted(symbols))
        quote_bundle = merge_position_marks(quote_bundle, nav_state.get("positions") or [])
        option_quote_bundle = fetch_option_quotes(nav_state.get("positions") or [])

    focus = focus or {}
    focus_type = (focus.get("type") or "").strip().lower()
    focused_story: Optional[dict] = None
    focused_item: Optional[dict] = None

    if focus_type == "story":
        idx = int(focus.get("story_index", 0))
        if 0 <= idx < len(stories):
            focused_story = _trim_story(stories[idx], full=True)
    elif focus_type == "plan_item":
        pid = focus.get("plan_item_id")
        if pid and current_plan:
            for it in current_plan.get("items") or []:
                if int(it.get("id") or 0) == int(pid):
                    focused_item = _compact_plan_item(it)
                    break
        if not focused_item and pid:
            row = store.get_plan_item(int(pid), portfolio_id)
            if row:
                focused_item = _compact_plan_item(row)

    if include_full_analysis or focus_type == "story":
        analysis_stories = stories
    else:
        analysis_stories = [_trim_story(s, full=False) for s in stories]

    plan_as_of = datetime.now().date()

    tier_discipline = None
    try:
        from core.tier_discipline import get_discipline_summary

        tier_discipline = get_discipline_summary(portfolio_id)
    except Exception:
        tier_discipline = None

    return {
        "household_id": household_id,
        "portfolio_id": portfolio_id,
        "plan_as_of": plan_as_of.isoformat(),
        "session": {"name": session.get("name"), "started_at": session.get("started_at")},
        "analysis_run": {
            "id": run["id"],
            "run_at": run["run_at"],
            "story_count": len(stories),
        },
        "analysis_stories": analysis_stories,
        "rules": rules,
        "nav_state": {
            "cash_usd": nav_state["cash_usd"],
            "cash_pct": nav_state["cash_pct"],
            "nav_usd": nav_state["nav_usd"],
            "positions": nav_state.get("positions") or [],
            "open_option_positions": open_option_count(nav_state.get("positions") or []),
            "new_positions_this_week": new_pos_week,
        },
        "current_plan": _compact_plan(current_plan),
        "recent_plans": recent_plans,
        "last_plan_timing": timing,
        "market_quotes": quote_bundle,
        "option_quotes": option_quote_bundle,
        "quotes_prompt": format_quotes_for_prompt(quote_bundle),
        "option_quotes_prompt": format_option_quotes_for_prompt(option_quote_bundle),
        "focus": focus,
        "focused_story": focused_story,
        "focused_plan_item": focused_item,
        "tier_discipline": tier_discipline,
        "_raw": {
            "analysis_run": run,
            "current_plan": current_plan,
            "nav_state": nav_state,
        },
    }


def format_context_for_plan_prompt(ctx: dict[str, Any]) -> dict[str, str]:
    """Strings for trader plan synthesis prompt."""
    nav = ctx["nav_state"]
    run = ctx["_raw"]["analysis_run"]
    stories_json = json.dumps(run.get("payload") or [], indent=2)[:120000]
    return {
        "timing_json": json.dumps(ctx["last_plan_timing"], indent=2),
        "recent_plans_json": json.dumps(ctx["recent_plans"], indent=2) if ctx["recent_plans"] else "[]",
        "quotes_json": ctx["quotes_prompt"],
        "option_quotes_json": ctx.get("option_quotes_prompt") or "[]",
        "rules_json": json.dumps(ctx["rules"], indent=2),
        "stories_json": stories_json,
        "nav_positions_json": json.dumps(nav.get("positions") or [], indent=2),
        "plan_as_of_iso": ctx["plan_as_of"],
    }
