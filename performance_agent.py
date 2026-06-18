"""Performance and lessons-learned reports."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from typing import Any, List, Optional

from anthropic import Anthropic
import config
from analysis_agent import AnalysisAgent
from core import store
from core.db import db_session, row_to_dict
from core.portfolio import compute_nav
from core.snapshots import get_nav_history


def _parse_utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _sanitize_nav_history(
    history: List[dict],
    *,
    initial_cash: float,
    current_nav: float,
) -> List[dict]:
    """Drop obvious snapshot spikes/resets so lessons focus on real trading."""
    if not history:
        return []

    values = [float(h.get("nav_usd") or 0) for h in history if h.get("nav_usd")]
    if not values:
        return history

    median_nav = statistics.median(values)
    ceiling = max(current_nav, initial_cash) * 2.5
    floor = min(initial_cash, current_nav) * 0.5
    tol = 0.02

    cleaned: List[dict] = []
    for row in history:
        nav = float(row.get("nav_usd") or 0)
        if nav > ceiling or nav < floor:
            continue
        if abs(nav - initial_cash) <= tol and current_nav > initial_cash + tol:
            continue
        if median_nav > 0 and nav > median_nav * 3:
            continue
        cleaned.append(row)
    return cleaned or history[-5:]


def _commit_tracking(portfolio_id: int, commit_hours: float) -> dict[str, Any]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT le.id, le.logged_at, le.ticker, le.side, le.plan_item_id,
                   d.decided_at, d.decision
            FROM ledger_events le
            LEFT JOIN decisions d ON d.plan_item_id = le.plan_item_id
                AND d.decision = 'accepted'
            WHERE le.portfolio_id = ? AND le.event_type = 'trade'
            ORDER BY le.logged_at, le.id
            """,
            (portfolio_id,),
        ).fetchall()

    within = 0
    after = 0
    unlinked = 0
    examples: List[dict] = []

    for row in rows:
        ev = row_to_dict(row) or {}
        pid = ev.get("plan_item_id")
        decided_at = ev.get("decided_at")
        if not pid or not decided_at:
            unlinked += 1
            continue
        trade_at = _parse_utc(ev["logged_at"])
        accept_at = _parse_utc(decided_at)
        hours = (trade_at - accept_at).total_seconds() / 3600.0
        on_time = hours <= commit_hours
        if on_time:
            within += 1
        else:
            after += 1
        if len(examples) < 8:
            examples.append(
                {
                    "ticker": ev.get("ticker"),
                    "side": ev.get("side"),
                    "hours_after_acceptance": round(hours, 1),
                    "within_commit_window": on_time,
                }
            )

    linked = within + after
    return {
        "commit_hours": commit_hours,
        "linked_trades": linked,
        "within_commit_window": within,
        "after_commit_window": after,
        "unlinked_trades": unlinked,
        "commit_rate_pct": round(within / linked * 100, 1) if linked else None,
        "examples": examples,
    }


class PerformanceAgent:
    def __init__(self):
        self.client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL
        self._parser = AnalysisAgent()

    def gather_metrics(self, portfolio_id: int) -> dict[str, Any]:
        nav = compute_nav(portfolio_id)
        raw_history = get_nav_history(portfolio_id)
        with db_session() as conn:
            port = conn.execute(
                "SELECT initial_cash FROM portfolios WHERE id = ?", (portfolio_id,)
            ).fetchone()
            initial_cash = float(port["initial_cash"]) if port else 1000.0

            trades = conn.execute(
                """
                SELECT * FROM ledger_events
                WHERE portfolio_id = ? AND event_type = 'trade'
                ORDER BY logged_at
                """,
                (portfolio_id,),
            ).fetchall()
            decisions = conn.execute(
                """
                SELECT d.*, pi.action, pi.ticker FROM decisions d
                JOIN plan_items pi ON pi.id = d.plan_item_id
                JOIN weekly_plans wp ON wp.id = pi.weekly_plan_id
                WHERE wp.portfolio_id = ?
                """,
                (portfolio_id,),
            ).fetchall()

        session = store.get_active_session()
        rules = store.get_portfolio_rules(
            portfolio_id, session["rules_json"] if session else "{}"
        )
        commit_hours = float(rules.get("trade_commit_hours", 24))
        commit = _commit_tracking(portfolio_id, commit_hours)
        nav_history = _sanitize_nav_history(
            raw_history,
            initial_cash=initial_cash,
            current_nav=float(nav["nav_usd"]),
        )

        accepted = sum(1 for d in decisions if d["decision"] == "accepted")
        rejected = sum(1 for d in decisions if d["decision"] == "rejected")
        total_dec = len(decisions)

        return {
            "nav": nav,
            "nav_history": nav_history,
            "nav_history_note": (
                "nav_history excludes legacy snapshot spikes and hard resets; "
                "use nav.positions and ledger trades as source of truth."
            ),
            "trade_count": len(trades),
            "decisions": {
                "total": total_dec,
                "accepted": accepted,
                "rejected": rejected,
                "acceptance_rate": (accepted / total_dec) if total_dec else None,
            },
            "commit_tracking": commit,
            "trades_within_24h": commit["within_commit_window"],
            "trades_after_24h": commit["after_commit_window"],
        }

    def generate_lessons_report(
        self,
        portfolio_id: int,
        household_id: int = 1,
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        metrics = self.gather_metrics(portfolio_id)
        session = store.get_active_session()
        rules = store.get_portfolio_rules(portfolio_id, session["rules_json"] if session else "{}")

        prompt = f"""You are reviewing a household paper-trading portfolio (executed manually in Sofi).

Metrics:
{json.dumps(metrics, indent=2, default=str)}

Trading rules:
{json.dumps(rules, indent=2)}

Write a lessons-learned report as JSON only:
{{
  "summary": "...",
  "what_worked": ["..."],
  "what_failed": ["..."],
  "process_improvements": ["..."],
  "risk_observations": ["..."]
}}

Guidelines:
- Focus on trading patterns: sector/theme concentration, position sizing vs rules, acceptance discipline, tier usage, and open-position P&L.
- Use commit_tracking for whether trades were logged within the commit window after acceptance (not raw DB nulls).
- nav_history may omit legacy snapshot artifacts; do NOT center the report on phantom NAV spikes or portfolio hard resets unless they are the only story.
- Treat nav.positions and the trade ledger as ground truth for current holdings.
No SPY benchmark. Be specific to the data provided."""

        message = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = self._parser._extract_response_text(message)
        report = self._parser._parse_json_object(text)
        report["metrics"] = metrics

        if persist:
            store.save_insight_report(
                household_id,
                report,
                portfolio_id=portfolio_id,
                report_type="lessons",
            )
        return report
