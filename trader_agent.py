"""Trader agent: on-demand trading plan per portfolio from analysis + holdings."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from anthropic import Anthropic
from anthropic import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
import random
import time

import config
from analysis_agent import AnalysisAgent
from core.plan_coherence import apply_plan_item_coherence
from core.plan_recency import last_plan_timing_block
from core.market_quotes import (
    collect_symbols_for_quotes,
    ensure_quotes_for_tickers,
    fetch_market_quotes,
    format_quotes_for_prompt,
    merge_position_marks,
    quotes_price_map,
)
from core.plan_sizing import normalize_plan_item_sizing, reconcile_stock_sizing_with_quote
from core.portfolio import compute_nav, open_option_count
from core.rules import parse_rules
from core import store
from pipeline.progress import ProgressCallback, emit_progress


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
        on_progress: Optional[ProgressCallback] = None,
    ) -> dict[str, Any]:
        emit_progress(on_progress, "start", "Starting trading plan generation")

        emit_progress(on_progress, "session", "Loading active household session…")
        session = store.get_active_session()
        if not session:
            raise RuntimeError("No active session. Run scripts/seed_household.py first.")

        emit_progress(on_progress, "analysis", "Loading latest analysis run for plan context…")
        run = (
            store.get_analysis_run(analysis_run_id)
            if analysis_run_id
            else store.get_latest_analysis_run(session["household_id"])
        )
        if not run or not run.get("payload"):
            raise RuntimeError("No analysis run available. Run daily analysis first.")

        stories = run.get("payload") or []
        emit_progress(
            on_progress,
            "analysis",
            f"Using analysis_run_id={run['id']} ({len(stories)} stories, run at {run['run_at']})",
            set_stage=False,
        )

        emit_progress(on_progress, "rules", "Loading portfolio trading rules…")
        rules = store.get_portfolio_rules(portfolio_id, session["rules_json"])

        emit_progress(on_progress, "portfolio", "Computing NAV and open positions…")
        nav_state = compute_nav(portfolio_id)
        new_pos_week = store.count_new_positions_this_week(portfolio_id)
        pos_count = len(nav_state.get("positions") or [])
        emit_progress(
            on_progress,
            "portfolio",
            (
                f"NAV ${nav_state['nav_usd']:.2f} · cash ${nav_state['cash_usd']:.2f} "
                f"({nav_state['cash_pct']:.1f}%) · {pos_count} position(s) · "
                f"{new_pos_week} new position(s) this week (Pacific)"
            ),
            set_stage=False,
        )

        emit_progress(on_progress, "history", "Loading recent trading plans and household decisions…")
        recent_plans = store.get_recent_weekly_plans_context(portfolio_id, limit=2)
        prior_plan = store.get_current_weekly_plan(portfolio_id)
        timing = last_plan_timing_block(
            plan_at=prior_plan.get("plan_at") if prior_plan else None,
            based_on_analysis_at=prior_plan.get("based_on_analysis_at") if prior_plan else None,
            current_analysis_at=run["run_at"],
            current_analysis_run_id=int(run["id"]),
            last_analysis_run_id=int(prior_plan["analysis_run_id"])
            if prior_plan and prior_plan.get("analysis_run_id")
            else None,
        )
        timing_json = json.dumps(timing, indent=2)
        hist_msg = f"{len(recent_plans)} prior plan(s) for continuity"
        if timing.get("has_prior_plan"):
            hist_msg += f" · last plan {timing.get('last_plan_ago_label')}"
        emit_progress(on_progress, "history", hist_msg, set_stage=False)
        recent_plans_json = json.dumps(recent_plans, indent=2) if recent_plans else "[]"

        emit_progress(on_progress, "quotes", "Fetching live quotes for analysis tickers…")
        quote_symbols = collect_symbols_for_quotes(stories, nav_state.get("positions"))
        quote_bundle = fetch_market_quotes(quote_symbols)
        quote_bundle = merge_position_marks(quote_bundle, nav_state.get("positions") or [])
        available = sum(1 for q in quote_bundle["quotes"].values() if q.get("available"))
        emit_progress(
            on_progress,
            "quotes",
            f"{available}/{len(quote_symbols)} quote(s) available (yfinance)",
            set_stage=False,
        )
        quotes_json = format_quotes_for_prompt(quote_bundle)

        plan_as_of = datetime.now().date()
        plan_as_of_iso = plan_as_of.isoformat()

        emit_progress(
            on_progress,
            "llm",
            f"Calling trader agent ({self.model}) to synthesize trading plan…",
        )

        max_indirect = getattr(config, "TRADER_MAX_INDIRECT_ITEMS_PER_PLAN", 1)
        min_conf_buy = getattr(config, "INDIRECT_MIN_CONFIDENCE_FOR_BUY", 6)

        prompt = f"""You are the household trader agent synthesizing an on-demand TRADING PLAN for ONE portfolio.

Plan as-of date (use for all month math): {plan_as_of_iso}

Execution happens manually in Sofi within 24 hours; this is a paper tracking book.

Cadence (IMPORTANT — read before anything else):
- There is NO fixed weekly or calendar schedule for plans. The household generates plans when they choose.
- Use "Last plan timing" below to see how long ago the most recent plan was produced and whether analysis has changed.
- If the last plan was generated recently AND latest news analysis has NOT materially changed since that plan's analysis timestamp (same run or same stories/theses), you SHOULD recommend NO portfolio changes:
  * Set no_changes: true
  * items: [] (empty array)
  * summary: 2–4 sentences explaining prior recommendations still stand and what would need to change before new trades (e.g. major news, risk shift, or portfolio drift).
- Only add or change line items when there is a clear NEW reason: material analysis delta, meaningful market move, rule/portfolio drift, or unresolved accepted/deferred commitments that need updates.
- Do NOT assume a new plan must differ from the last one — stability is correct when conditions are unchanged.

Last plan timing (ground truth from the database):
{timing_json}

Context policy (hybrid memory — follow strictly):
- FRESH evaluation: Use "Latest news analysis" below for current market stories and multi-persona theses only.
- GROUND TRUTH book: Use "Portfolio state" for cash, positions, and concrete sizing — not assumptions.
- SHORT household memory: Use "Recent trading plans and decisions" for continuity (not a weekly calendar).
  * Honor accepted and deferred items; do not flip-flop without explicit rationale tied to NEW analysis.
  * Do not repeat rejected recommendations unless the latest analysis clearly overrides the prior thesis.
  * Deferred items may stay on the plan with updated sizing or move to watch — explain why.
- Do NOT re-litigate old news from prior plans; prior plans are for commitments and decisions, not stale narratives.

Portfolio state:
- Cash: ${nav_state['cash_usd']:.2f} ({nav_state['cash_pct']:.1f}% of NAV)
- NAV: ${nav_state['nav_usd']:.2f}
- Positions: {json.dumps(nav_state['positions'], indent=2)}
- Open option positions: {open_option_count(nav_state['positions'])}
- New positions opened this week (Pacific): {new_pos_week}

Market quotes (REQUIRED for stock per-share math — same source as Portfolio marks; do NOT invent prices):
{quotes_json}

Trading rules (MUST NOT violate):
{json.dumps(rules, indent=2)}

Recent trading plans and decisions (newest first, up to 2 prior plans; each includes plan_ago_label):
{recent_plans_json}

Latest news analysis envelopes (multi-persona per story; each may include indirect_effects for macro stories):
{json.dumps(run['payload'], indent=2)[:120000]}

Indirect / 2nd-order effects (IMPORTANT — keep the plan coherent):
- Each story may include indirect_effects with causal_chains (hypotheses, not persona trades).
- You are the ONLY step that may action indirect ideas as plan line items.
- At most {max_indirect} item(s) in the entire plan may have thesis_type "indirect".
- For thesis_type "indirect", only include buy/sell/trim (not hold) when ALL hold:
  * Top ticker confidence >= {min_conf_buy} (from indirect_effects.causal_chains[].tickers[].confidence)
  * liquidity_ok is true for that chain
  * already_priced_risk is not "high"
  * Passes all portfolio rules below
- If confidence is 4–5, use action "watch" with thesis_type "indirect" (no new position).
- Prefer first-order items from analyst personas; skip indirect if the plan already has enough first-order trades unless indirect diversifies sector.
- rationale must cite the causal steps briefly; mention key falsifiers in rule_warnings if relevant.
- Do NOT copy aggressive alternative_plays as separate items if you already used that indirect thesis.

Produce ONE consolidated trading plan for this portfolio respecting rules:
- max {rules['max_position_pct_nav']}% NAV per position
- max {rules['max_new_positions_per_week']} NEW positions per week (already used: {new_pos_week})
- min {rules['cash_floor_pct']}% cash floor
- max {rules['max_open_option_positions']} open option positions at once
- options and shorts allowed

Horizon and options (MUST be internally consistent):
- horizon = expected THESIS window for the trade (when you expect the move / will re-evaluate):
  * short: ~2–8 weeks from plan date
  * medium: ~2–5 months from plan date
  * long: ~6–18 months from plan date
- expected_exit_months: numeric estimate within the horizon band above (e.g. 4 for a 3–4 month catalyst).
- Do NOT copy analyst story timelines into option expiry without converting to a real calendar date.
- For call_option / put_option you MUST include option_contract with expiry YYYY-MM-DD, strike, right, moneyness (atm|otm|itm).
- option_contract.expiry must match the thesis:
  * Expiry on or after expected exit, but usually within expected_exit_months + 1–2 months (time buffer only).
  * Do NOT recommend LEAPS (e.g. expiry 9+ months out) for a medium/short (2–5 month) thesis — that over-pays for time.
  * Example: plan date {plan_as_of_iso}, 3–4 month thesis → expiry roughly {plan_as_of_iso[:7]} + 4–6 months, NOT the next calendar year LEAP unless horizon is long.
- If you want long-dated exposure, set horizon to long and explain in rationale.

Sizing (REQUIRED for every item except watch/hold with no trade):
- Use concrete dollar amounts and/or share/contract counts grounded in current cash, NAV, open positions, and market_quotes.
- For STOCKS: use ONLY market_quotes[SYMBOL].price_usd for per-share price in sizing.summary (e.g. "@ ~$135.50"). Never guess from memory.
- If market_quotes[SYMBOL].price_usd is null, state pct_nav/pct_cash only — do not invent a share price.
- notional_usd should equal quantity × price_usd (approximately) for stock buys.
- Do NOT rely on vague labels like small/medium/large as the primary guidance.
- For buys: notional_usd and quantity (shares or contracts); pct_cash and pct_nav when helpful.
- For trim/sell: pct_position and/or quantity; notional_usd estimate using market_quotes when useful.
- For options: quantity in contracts; sizing.summary must repeat strike + expiry from option_contract (options are not in market_quotes).
- sizing.summary: one human-readable line (e.g. "Buy ~$271 (2 shares @ ~$135.50); ~27% of cash, ~12% of NAV").
- Respect cash floor and max position %; mention conflicts in rule_warnings.

Return valid JSON only:
{{
  "summary": "2-4 sentences",
  "no_changes": false,
  "based_on_analysis_at": "{run['run_at']}",
  "items": [
    {{
      "priority": 1,
      "thesis_type": "first_order|indirect",
      "action": "buy|sell|trim|hedge|hold|watch",
      "ticker": "SYMBOL or null",
      "instrument_type": "stock|call_option|put_option",
      "horizon": "short|medium|long",
      "expected_exit_months": 4.0,
      "option_contract": {{
        "underlying": "SPY",
        "expiry": "2026-10-16",
        "strike": 550.0,
        "right": "call|put",
        "moneyness": "otm|atm|itm"
      }},
      "size_hint": "optional qualitative tag only — not a substitute for sizing",
      "sizing": {{
        "notional_usd": 330.0,
        "quantity": 2,
        "quantity_unit": "shares|contracts",
        "pct_nav": 12.5,
        "pct_cash": 33.0,
        "pct_position": null,
        "summary": "Buy ~$330 (2 shares @ ~$165); ~33% of cash"
      }},
      "persona_consensus": {{"aggressive": true, "moderate": false, "minimal_risk": false}},
      "rationale": "...",
      "rule_warnings": ["optional warnings if sizing might breach rules"]
    }}
  ]
}}
Limit items to at most 8. Prefer liquid US names. If no portfolio changes warranted, set no_changes true and items [] (the system will keep existing open recommendations from the prior plan).
Default thesis_type to "first_order" for persona-driven trades.
For stocks (not options), omit option_contract and expected_exit_months is optional."""

        text = self._message_create(prompt)
        emit_progress(on_progress, "parse", "Parsing trader agent JSON response…")
        parsed = self._parser._parse_json_object(text)
        parsed["based_on_analysis_at"] = run["run_at"]
        parsed["generated_at"] = store.utc_now_iso()
        parsed["portfolio_id"] = portfolio_id
        parsed["analysis_run_id"] = run["id"]
        parsed["market_quotes"] = quote_bundle

        price_map = quotes_price_map(quote_bundle)
        plan_tickers = [
            (raw.get("ticker") or "").strip().upper()
            for raw in parsed.get("items") or []
            if raw.get("ticker")
        ]
        ensure_quotes_for_tickers(quote_bundle, plan_tickers)
        price_map = quotes_price_map(quote_bundle)

        items = []
        indirect_count = 0
        max_indirect = getattr(config, "TRADER_MAX_INDIRECT_ITEMS_PER_PLAN", 1)
        for raw in parsed.get("items") or []:
            item = normalize_plan_item_sizing(dict(raw))
            sym = (item.get("ticker") or "").strip().upper()
            live = price_map.get(sym)
            if live:
                item = reconcile_stock_sizing_with_quote(item, live, nav_state)
                item = normalize_plan_item_sizing(item)
            if (item.get("thesis_type") or "first_order").strip().lower() == "indirect":
                if indirect_count >= max_indirect:
                    item["thesis_type"] = "first_order"
                    warnings = list(item.get("rule_warnings") or [])
                    warnings.append(
                        f"Exceeded max {max_indirect} indirect item(s); treated as first_order"
                    )
                    item["rule_warnings"] = warnings
                else:
                    indirect_count += 1
            else:
                item.setdefault("thesis_type", "first_order")
            item = apply_plan_item_coherence(item, plan_as_of)
            items.append(item)
        parsed["items"] = items
        no_changes = bool(parsed.get("no_changes") or parsed.get("no_trade_week"))
        parsed["no_changes"] = no_changes
        parsed["no_trade_week"] = no_changes
        parsed["last_plan_timing"] = timing
        emit_progress(
            on_progress,
            "parse",
            f"Plan draft: {len(items)} item(s)" + (" · no changes recommended" if no_changes else ""),
            set_stage=False,
        )

        prior_items = (prior_plan or {}).get("items") or []
        reuse_prior = (
            no_changes
            and not items
            and prior_plan
            and prior_items
            and int(prior_plan.get("id") or 0) > 0
        )

        if reuse_prior:
            plan_id = int(prior_plan["id"])
            emit_progress(
                on_progress,
                "persist",
                f"No new items — updating plan #{plan_id} and keeping {len(prior_items)} open recommendation(s)…",
            )
            store.update_weekly_plan_evaluation(
                plan_id,
                portfolio_id=portfolio_id,
                analysis_run_id=run["id"],
                based_on_analysis_at=run["run_at"],
                trigger_type=trigger_type,
                summary=parsed.get("summary", ""),
                payload=parsed,
            )
            refreshed = store.get_weekly_plan_by_id(plan_id, portfolio_id)
            parsed["weekly_plan_id"] = plan_id
            parsed["items"] = (refreshed or {}).get("items") or prior_items
            parsed["carried_forward"] = True
            item_count = len(parsed["items"])
        else:
            emit_progress(on_progress, "persist", "Saving trading plan and recommendation items…")
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
            item_count = len(items)

        summary = (parsed.get("summary") or "")[:120]
        emit_progress(
            on_progress,
            "done",
            f"Saved trading_plan_id={plan_id} · {item_count} item(s). {summary}",
            set_stage=True,
        )
        return parsed
