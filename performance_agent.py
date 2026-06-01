"""Performance and lessons-learned reports."""

from __future__ import annotations

import json
from typing import Any, Optional

from anthropic import Anthropic
import config
from analysis_agent import AnalysisAgent
from core import store
from core.portfolio import compute_nav
from core.snapshots import get_nav_history
from core.db import db_session


class PerformanceAgent:
    def __init__(self):
        self.client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL
        self._parser = AnalysisAgent()

    def gather_metrics(self, portfolio_id: int) -> dict[str, Any]:
        nav = compute_nav(portfolio_id)
        history = get_nav_history(portfolio_id)
        with db_session() as conn:
            trades = conn.execute(
                """
                SELECT * FROM ledger_events WHERE portfolio_id = ? ORDER BY logged_at
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

        accepted = sum(1 for d in decisions if d["decision"] == "accepted")
        rejected = sum(1 for d in decisions if d["decision"] == "rejected")
        total_dec = len(decisions)

        return {
            "nav": nav,
            "nav_history": history,
            "trade_count": len(trades),
            "decisions": {
                "total": total_dec,
                "accepted": accepted,
                "rejected": rejected,
                "acceptance_rate": (accepted / total_dec) if total_dec else None,
            },
            "trades_within_24h": sum(1 for t in trades if t["executed_within_24h"] == 1),
            "trades_after_24h": sum(1 for t in trades if t["executed_within_24h"] == 0),
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
