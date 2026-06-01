"""Trader agent: weekly plan per portfolio from analysis + holdings."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from anthropic import Anthropic
from anthropic import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
import random
import time

import config
from analysis_agent import AnalysisAgent
from core.portfolio import compute_nav, open_option_count
from core.rules import parse_rules
from core import store


class TraderAgent:
    def __init__(self):
        self.client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL
        self._parser = AnalysisAgent()

    def _message_create(self, prompt: str, max_tokens: int = 8000) -> str:
        max_attempts = getattr(config, "ANTHROPIC_MAX_RETRIES", 6)
        base_delay = getattr(config, "ANTHROPIC_RETRY_BASE_DELAY_SEC", 2.0)
        last_exc = None
        for attempt in range(max_attempts):
            try:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return self._parser._extract_response_text(message)
            except Exception as e:
                last_exc = e
                if not self._parser._is_retryable_anthropic(e) or attempt == max_attempts - 1:
                    raise
                delay = base_delay * (2**attempt) + random.uniform(0, 1.5)
                time.sleep(delay)
        raise last_exc

    def build_weekly_plan(
        self,
        portfolio_id: int,
        *,
        analysis_run_id: Optional[int] = None,
        trigger_type: str = "manual",
    ) -> dict[str, Any]:
        session = store.get_active_session()
        if not session:
            raise RuntimeError("No active session. Run scripts/seed_household.py first.")

        run = (
            store.get_analysis_run(analysis_run_id)
            if analysis_run_id
            else store.get_latest_analysis_run(session["household_id"])
        )
        if not run or not run.get("payload"):
            raise RuntimeError("No analysis run available. Run daily analysis first.")

        rules = store.get_portfolio_rules(portfolio_id, session["rules_json"])
        nav_state = compute_nav(portfolio_id)
        new_pos_week = store.count_new_positions_this_week(portfolio_id)

        prompt = f"""You are the household trader agent synthesizing a weekly action plan for ONE portfolio.

Execution happens manually in Sofi within 24 hours; this is a paper tracking book.

Portfolio state:
- Cash: ${nav_state['cash_usd']:.2f} ({nav_state['cash_pct']:.1f}% of NAV)
- NAV: ${nav_state['nav_usd']:.2f}
- Positions: {json.dumps(nav_state['positions'], indent=2)}
- Open option positions: {open_option_count(nav_state['positions'])}
- New positions opened this week (Pacific): {new_pos_week}

Trading rules (MUST NOT violate):
{json.dumps(rules, indent=2)}

Latest news analysis envelopes (multi-persona per story):
{json.dumps(run['payload'], indent=2)[:120000]}

Produce ONE consolidated weekly plan for this portfolio respecting rules:
- max {rules['max_position_pct_nav']}% NAV per position
- max {rules['max_new_positions_per_week']} NEW positions per week (already used: {new_pos_week})
- min {rules['cash_floor_pct']}% cash floor
- max {rules['max_open_option_positions']} open option positions at once
- options and shorts allowed

Return valid JSON only:
{{
  "summary": "2-4 sentences",
  "no_trade_week": false,
  "based_on_analysis_at": "{run['run_at']}",
  "items": [
    {{
      "priority": 1,
      "action": "buy|sell|trim|hedge|hold|watch",
      "ticker": "SYMBOL or null",
      "instrument_type": "stock|call_option|put_option",
      "horizon": "short|medium|long",
      "size_hint": "small|medium|large",
      "persona_consensus": {{"aggressive": true, "moderate": false, "minimal_risk": false}},
      "rationale": "...",
      "rule_warnings": ["optional warnings if sizing might breach rules"]
    }}
  ]
}}
Limit items to at most 8. Prefer liquid US names. If no action, set no_trade_week true and empty items."""

        text = self._message_create(prompt)
        parsed = self._parser._parse_json_object(text)
        parsed["based_on_analysis_at"] = run["run_at"]
        parsed["generated_at"] = store.utc_now_iso()
        parsed["portfolio_id"] = portfolio_id
        parsed["analysis_run_id"] = run["id"]

        items = parsed.get("items") or []
        plan_id = store.create_weekly_plan(
            portfolio_id=portfolio_id,
            analysis_run_id=run["id"],
            based_on_analysis_at=run["run_at"],
            trigger_type=trigger_type,
            summary=parsed.get("summary", ""),
            payload=parsed,
            items=items,
        )
        parsed["weekly_plan_id"] = plan_id
        return parsed
