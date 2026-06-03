"""Weekly backtest: cached analysis -> trader agent -> paper execution -> weekly NAV."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backtest import cache as bt_cache
from backtest.calendar_util import (
    extended_trading_calendar,
    next_trading_day,
    trading_day_on_or_before,
    weekly_run_dates,
)
from backtest.config import DEFAULT_WEEKS
from backtest.historical_quotes import price_map_from_close, quote_bundle_for_date, symbols_from_context
from backtest.paper_book import PaperBook
from backtest.plan_execution import execute_plan_on_book, plan_items_for_report
from backtest.report import write_weekly_report
from backtest.tier_discipline_snapshot import snapshot_paper_discipline
from backtest.returns import fetch_adj_close
from backtest.runner import BacktestConfig, _fetch_or_load_news, _run_pipeline_for_day
from core.plan_recency import last_plan_timing_block
from core.rules import DEFAULT_RULES, parse_rules
from trader_agent import TraderAgent
from validation import collect_tickers_from_stories


@dataclass
class WeeklyBacktestResult:
    config: BacktestConfig
    run_dates: List[date]
    weekly_portfolio: List[Dict[str, Any]]
    report_path: Optional[str]
    details: Dict[str, Any] = field(default_factory=dict)


def _analysis_run_at(run_day: date) -> str:
    return f"{run_day.isoformat()}T18:00:00+00:00"


def _plan_to_recent_context(plan: dict, run_day: date) -> dict:
    return {
        "plan_at": plan.get("generated_at") or _analysis_run_at(run_day),
        "plan_ago_label": "about 1 week ago",
        "based_on_analysis_at": plan.get("based_on_analysis_at"),
        "summary": plan.get("summary"),
        "no_changes": plan.get("no_changes"),
        "items": [
            {
                **item,
                "status": "accepted",
                "decision": "accepted",
                "decision_note": "backtest: all trader recommendations accepted",
            }
            for item in plan.get("items") or []
        ],
    }


def _week_mark_day(
    trade_day: date,
    run_index: int,
    run_dates: List[date],
    calendar: List[date],
) -> date:
    """Last trading session of this holding week (before next run)."""
    if run_index < len(run_dates) - 1:
        next_run = run_dates[run_index + 1]
        candidates = [d for d in calendar if trade_day <= d < next_run]
        if candidates:
            return candidates[-1]
    candidates = [d for d in calendar if d >= trade_day]
    return candidates[-1] if candidates else trade_day


def _merge_close(close, symbols: List[str], start: date, end: date):
    import pandas as pd

    if close is None or close.empty:
        return fetch_adj_close(symbols, start, end)
    missing = [s for s in symbols if s not in close.columns]
    if not missing:
        return close
    extra = fetch_adj_close(missing, start, end)
    if extra is None or extra.empty:
        return close
    return close.join(extra, how="outer") if not close.empty else extra


async def _load_or_run_analysis(run_day: date, cfg: BacktestConfig) -> dict:
    if cfg.trader_only:
        cached = bt_cache.load_cached_run(run_day)
        if not cached:
            raise RuntimeError(
                f"No cached analysis for {run_day}. "
                f"Expected data/backtest/cache/runs/{run_day.isoformat()}.json"
            )
        return cached

    if cfg.skip_llm:
        cached = bt_cache.load_cached_run(run_day)
        if cached:
            return cached
        raise RuntimeError(f"No cached analysis for {run_day} with --skip-llm")

    articles = await _fetch_or_load_news(run_day, cfg)
    if not articles:
        payload = {
            "as_of": run_day.isoformat(),
            "article_count": 0,
            "story_count": 0,
            "analyses": [],
        }
        bt_cache.save_cached_run(run_day, payload)
        return payload
    return await _run_pipeline_for_day(run_day, articles, cfg)


async def run_weekly_backtest(cfg: BacktestConfig) -> WeeklyBacktestResult:
    weeks = cfg.weeks or DEFAULT_WEEKS
    run_dates = weekly_run_dates(cfg.end_date, weeks)
    if not run_dates:
        raise ValueError("No weekly run dates")

    log = (lambda *a, **k: None) if cfg.quiet else print
    rules = parse_rules(DEFAULT_RULES)
    book = PaperBook(cash_usd=cfg.initial_capital)
    recent_plans: List[dict] = []
    prior_plan: Optional[dict] = None
    plans_by_week: Dict[str, dict] = {}
    execution_logs: List[dict] = []
    weekly_portfolio: List[Dict[str, Any]] = [
        {
            "week": 0,
            "run_date": None,
            "as_of": run_dates[0].isoformat(),
            "portfolio_usd": round(cfg.initial_capital, 2),
            "plan_items": 0,
        }
    ]

    sim_cal = extended_trading_calendar(
        run_dates[0],
        run_dates[-1],
        hold_trading_days=cfg.hold_trading_days,
    )
    close = None

    for i, run_day in enumerate(run_dates):
        week_num = i + 1
        log(f"[week {week_num}/{len(run_dates)}] run date {run_day.isoformat()}")

        if cfg.fetch_news_only:
            await _fetch_or_load_news(run_day, cfg)
            continue

        book.reset_week_counter(run_day)
        payload = await _load_or_run_analysis(run_day, cfg)
        analyses = payload.get("analyses") or []
        log(f"  analysis: {len(analyses)} stories from cache/pipeline")

        symbols = set(collect_tickers_from_stories(analyses))
        for sym in book.positions:
            symbols.add(sym.upper())
        symbols.add("SPY")
        close = _merge_close(close, sorted(symbols), sim_cal[0], sim_cal[-1])

        plan = None
        if cfg.skip_trader or (not cfg.force_refresh_news):
            plan = bt_cache.load_cached_plan(run_day)
            if plan:
                log(f"  trader plan from cache ({len(plan.get('items') or [])} items)")
        if cfg.skip_trader and not plan:
            raise RuntimeError(
                f"No cached trader plan for {run_day}. "
                f"Run once without --skip-trader to generate data/backtest/cache/plans/"
            )
        if not plan:
            nav_state = book.nav_state(price_map_from_close(close, run_day))
            quote_symbols = symbols_from_context(analyses, nav_state.get("positions") or [])
            quote_bundle = quote_bundle_for_date(close, quote_symbols, run_day)
            analysis_run_at = _analysis_run_at(run_day)
            timing = last_plan_timing_block(
                plan_at=(prior_plan or {}).get("generated_at"),
                based_on_analysis_at=(prior_plan or {}).get("based_on_analysis_at"),
                current_analysis_at=analysis_run_at,
                current_analysis_run_id=week_num,
                last_analysis_run_id=week_num - 1 if prior_plan else None,
                now=datetime.fromisoformat(analysis_run_at.replace("Z", "+00:00")),
            )
            agent = TraderAgent()
            log("  trader agent (LLM)…")

            def _trader() -> dict:
                return agent.build_weekly_plan_backtest(
                    stories=analyses,
                    nav_state=nav_state,
                    rules=rules,
                    recent_plans=recent_plans,
                    prior_plan=prior_plan,
                    timing=timing,
                    quote_bundle=quote_bundle,
                    plan_as_of=run_day,
                    analysis_run_at=analysis_run_at,
                    new_pos_week=book.new_positions_this_week,
                )

            plan = await asyncio.to_thread(_trader)
            plan["run_date"] = run_day.isoformat()
            bt_cache.save_cached_plan(run_day, plan)
            log(
                f"  trader plan saved: {len(plan.get('items') or [])} items, "
                f"no_changes={plan.get('no_changes')}"
            )

        plans_by_week[run_day.isoformat()] = plan

        trade_day = next_trading_day(run_day, sim_cal) or run_day
        for item in plan.get("items") or []:
            t = (item.get("ticker") or "").strip().upper()
            if t and t not in close.columns:
                close = _merge_close(close, [t], sim_cal[0], sim_cal[-1])

        exec_log = execute_plan_on_book(book, plan, trade_date=trade_day, close=close)
        execution_logs.extend(exec_log)
        ok_count = sum(1 for e in exec_log if e.get("ok"))
        log(f"  executed {ok_count}/{len(exec_log)} plan trades (session {trade_day})")

        mark_day = _week_mark_day(trade_day, i, run_dates, sim_cal)
        marks = price_map_from_close(close, mark_day)
        nav = book.mark_nav(marks)
        discipline = snapshot_paper_discipline(
            book.nav_state(marks)["positions"],
            plan.get("items") or [],
            mark_day,
        )
        if discipline:
            execution_logs.append(
                {"type": "tier_discipline", "run_date": run_day.isoformat(), "items": discipline}
            )
        weekly_portfolio.append(
            {
                "week": week_num,
                "run_date": run_day.isoformat(),
                "as_of": mark_day.isoformat(),
                "portfolio_usd": round(nav, 2),
                "plan_items": len(plan_items_for_report(plan)),
                "no_changes": bool(plan.get("no_changes")),
                "summary": (plan.get("summary") or "")[:200],
            }
        )

        prior_plan = plan
        recent_plans = [_plan_to_recent_context(plan, run_day)] + recent_plans[:1]

    if cfg.fetch_news_only:
        return WeeklyBacktestResult(
            config=cfg,
            run_dates=run_dates,
            weekly_portfolio=[],
            report_path=None,
            details={"news_only": True},
        )

    start_nav = cfg.initial_capital
    end_nav = weekly_portfolio[-1]["portfolio_usd"] if len(weekly_portfolio) > 1 else start_nav
    ret_pct = (end_nav - start_nav) / start_nav * 100 if start_nav else 0.0

    report_path = write_weekly_report(
        cfg=cfg,
        run_dates=run_dates,
        weekly_portfolio=weekly_portfolio,
        plans_by_week=plans_by_week,
        execution_logs=execution_logs,
        total_return_pct=ret_pct,
        output_path=cfg.output_path,
        json_stdout=cfg.json_stdout,
        terminal=not cfg.json_stdout,
    )

    return WeeklyBacktestResult(
        config=cfg,
        run_dates=run_dates,
        weekly_portfolio=weekly_portfolio,
        report_path=report_path,
        details={"total_return_pct": round(ret_pct, 4), "execution_logs": execution_logs},
    )
