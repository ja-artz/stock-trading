"""Orchestrate historical backtest day-by-day."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from news_collector import NewsCollector

from backtest import cache as bt_cache
from backtest.config import (
    DEFAULT_DAYS,
    DEFAULT_END_DATE,
    DEFAULT_HOLD_TRADING_DAYS,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_NEWS_QUERY,
    DEFAULT_PERSONA,
    DEFAULT_RANDOM_SEED,
    RESULTS_DIR,
)
from backtest.calendar_util import extended_trading_calendar, trading_days_between
from backtest.returns import (
    build_ticker_universe,
    buy_and_hold_return,
    equal_weight_day_return,
    fetch_adj_close,
    simulate_signals,
)
from backtest.signals import (
    extract_recommendations,
    mentioned_tickers,
)
from pipeline.daily_analysis import run_daily_analysis


@dataclass
class BacktestConfig:
    end_date: date = field(default_factory=lambda: date.fromisoformat(DEFAULT_END_DATE))
    days: int = DEFAULT_DAYS
    hold_trading_days: int = DEFAULT_HOLD_TRADING_DAYS
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    persona: str = DEFAULT_PERSONA
    news_query: str = DEFAULT_NEWS_QUERY
    random_seed: int = DEFAULT_RANDOM_SEED
    fetch_news_only: bool = False
    skip_llm: bool = False
    force_refresh_news: bool = False
    max_days: Optional[int] = None  # cap for smoke tests
    weeks: int = 13
    weekly: bool = True
    trader_only: bool = False
    skip_trader: bool = False
    output_path: Optional[str] = None
    quiet: bool = False
    json_stdout: bool = False


@dataclass
class BacktestResult:
    config: BacktestConfig
    start_date: date
    end_date: date
    trading_days: List[date]
    strategy_return_pct: float
    spy_return_pct: Optional[float]
    equal_weight_mentioned_return_pct: float
    random_return_pct: float
    total_signals: int
    days_with_signals: int
    report_path: Optional[str]
    details: Dict[str, Any] = field(default_factory=dict)


def _calendar_days(cfg: BacktestConfig) -> List[date]:
    start = cfg.end_date - timedelta(days=cfg.days - 1)
    days = trading_days_between(start, cfg.end_date)
    if cfg.max_days is not None:
        days = days[-cfg.max_days :]
    return days


async def _fetch_or_load_news(day: date, cfg: BacktestConfig) -> List[dict]:
    if not cfg.force_refresh_news:
        cached = bt_cache.load_cached_news(day)
        if cached is not None:
            return cached
    collector = NewsCollector(
        rss_url="https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        max_age_hours=0,
    )

    def _fetch() -> List[dict]:
        return collector.fetch_news_for_date(
            day,
            query=cfg.news_query,
            num_results=30,
        )

    articles = await asyncio.to_thread(_fetch)
    bt_cache.save_cached_news(day, articles)
    return articles


async def _run_pipeline_for_day(
    day: date,
    articles: List[dict],
    cfg: BacktestConfig,
) -> dict:
    if not cfg.force_refresh_news:
        cached = bt_cache.load_cached_run(day)
        if cached is not None:
            return cached

    result = await run_daily_analysis(
        persist=False,
        export=False,
        run_type="backtest",
        articles=articles,
    )
    payload = {
        "as_of": day.isoformat(),
        "article_count": result.article_count,
        "story_count": result.story_count,
        "analyses": result.analyses,
    }
    bt_cache.save_cached_run(day, payload)
    return payload


async def run_backtest(cfg: BacktestConfig) -> BacktestResult:
    if cfg.weekly:
        from backtest.weekly_runner import run_weekly_backtest

        weekly = await run_weekly_backtest(cfg)
        return BacktestResult(
            config=cfg,
            start_date=weekly.run_dates[0] if weekly.run_dates else cfg.end_date,
            end_date=weekly.run_dates[-1] if weekly.run_dates else cfg.end_date,
            trading_days=weekly.run_dates,
            strategy_return_pct=_weekly_total_return(weekly),
            spy_return_pct=None,
            equal_weight_mentioned_return_pct=0.0,
            random_return_pct=0.0,
            total_signals=sum(
                w.get("signals", 0) for w in weekly.weekly_portfolio if w.get("week", 0) > 0
            ),
            days_with_signals=sum(
                1 for w in weekly.weekly_portfolio if w.get("week", 0) > 0 and w.get("signals")
            ),
            report_path=weekly.report_path,
            details={"weekly_portfolio": weekly.weekly_portfolio, **weekly.details},
        )

    calendar = _calendar_days(cfg)
    if not calendar:
        raise ValueError("No trading days in backtest window")

    start_date = calendar[0]
    end_date = calendar[-1]

    signals_by_day: Dict[date, List] = {}
    mentioned_by_day: Dict[date, List[str]] = {}

    log = (lambda *a, **k: None) if cfg.quiet else print

    for i, day in enumerate(calendar, 1):
        log(f"[{i}/{len(calendar)}] {day.isoformat()} — news + pipeline")
        articles = await _fetch_or_load_news(day, cfg)
        if cfg.fetch_news_only:
            continue
        if cfg.skip_llm:
            cached = bt_cache.load_cached_run(day)
            if not cached:
                log(f"  skip_llm: no cached run for {day}, skipping")
                continue
            payload = cached
        else:
            if not articles:
                log("  no articles for this day")
                bt_cache.save_cached_run(
                    day,
                    {"as_of": day.isoformat(), "article_count": 0, "story_count": 0, "analyses": []},
                )
                payload = {"analyses": []}
            else:
                payload = await _run_pipeline_for_day(day, articles, cfg)

        analyses = payload.get("analyses") or []
        sigs = extract_recommendations(analyses, day, persona=cfg.persona)
        signals_by_day[day] = sigs
        mentioned_by_day[day] = mentioned_tickers(analyses)
        log(f"  signals={len(sigs)} mentioned={len(mentioned_by_day[day])}")

    if cfg.fetch_news_only:
        return BacktestResult(
            config=cfg,
            start_date=start_date,
            end_date=end_date,
            trading_days=calendar,
            strategy_return_pct=0.0,
            spy_return_pct=None,
            equal_weight_mentioned_return_pct=0.0,
            random_return_pct=0.0,
            total_signals=0,
            days_with_signals=0,
            report_path=None,
            details={"news_only": True},
        )

    universe = build_ticker_universe(signals_by_day, mentioned_by_day)
    sim_cal = extended_trading_calendar(start_date, end_date, hold_trading_days=cfg.hold_trading_days)
    close = fetch_adj_close(sorted(universe), sim_cal[0], sim_cal[-1])

    strategy_sim = simulate_signals(
        signals_by_day,
        calendar=sim_cal,
        close=close,
        initial_capital=cfg.initial_capital,
        hold_trading_days=cfg.hold_trading_days,
        signal_days=calendar,
    )
    strategy_return = strategy_sim.total_return_pct()

    spy_ret = buy_and_hold_return(close, "SPY", start_date, end_date, calendar=sim_cal)

    eq_mentioned_daily: List[Optional[float]] = []
    rng = random.Random(cfg.random_seed)
    random_daily: List[Optional[float]] = []
    ticker_universe = sorted(universe - {"SPY"})

    for day in calendar:
        sigs = signals_by_day.get(day, [])
        mentioned = mentioned_by_day.get(day, [])
        eq_mentioned_daily.append(
            equal_weight_day_return(
                close, mentioned, day, cfg.hold_trading_days, sim_cal
            )
        )
        n = len(sigs)
        if n > 0 and len(ticker_universe) >= n:
            picks = rng.sample(ticker_universe, n)
        elif n > 0:
            picks = [rng.choice(ticker_universe) for _ in range(n)]
        else:
            picks = []
        random_daily.append(
            equal_weight_day_return(close, picks, day, cfg.hold_trading_days, sim_cal)
            if picks
            else None
        )

    # Compound non-overlapping daily cohort returns (days with tickers only)
    eq_returns = [r for r in eq_mentioned_daily if r is not None]
    if eq_returns:
        eq_final = cfg.initial_capital
        for r in eq_returns:
            eq_final *= 1.0 + r
        eq_mentioned_pct = (eq_final - cfg.initial_capital) / cfg.initial_capital * 100.0
    else:
        eq_mentioned_pct = 0.0

    rand_returns = [r for r in random_daily if r is not None]
    if rand_returns:
        rand_final = cfg.initial_capital
        for r in rand_returns:
            rand_final *= 1.0 + r
        random_pct = (rand_final - cfg.initial_capital) / cfg.initial_capital * 100.0
    else:
        random_pct = 0.0

    total_signals = sum(len(v) for v in signals_by_day.values())
    days_with_signals = sum(1 for v in signals_by_day.values() if v)

    from backtest.report import write_report

    out = Path(cfg.output_path) if cfg.output_path else None
    report_path = write_report(
        cfg=cfg,
        calendar=calendar,
        strategy_sim=strategy_sim,
        strategy_return=strategy_return,
        spy_return=spy_ret,
        equal_weight_mentioned_pct=eq_mentioned_pct,
        random_pct=random_pct,
        signals_by_day=signals_by_day,
        mentioned_by_day=mentioned_by_day,
        output_path=out,
        terminal=not cfg.json_stdout,
        json_stdout=cfg.json_stdout,
    )

    return BacktestResult(
        config=cfg,
        start_date=start_date,
        end_date=end_date,
        trading_days=calendar,
        strategy_return_pct=strategy_return,
        spy_return_pct=spy_ret,
        equal_weight_mentioned_return_pct=eq_mentioned_pct,
        random_return_pct=random_pct,
        total_signals=total_signals,
        days_with_signals=days_with_signals,
        report_path=report_path,
        details={
            "closed_trades": len(strategy_sim.closed),
            "final_equity": strategy_sim.equity_history[-1].equity_usd
            if strategy_sim.equity_history
            else cfg.initial_capital,
        },
    )


def _weekly_total_return(weekly) -> float:
    pts = weekly.weekly_portfolio
    if len(pts) < 2:
        return 0.0
    start = pts[0]["portfolio_usd"]
    end = pts[-1]["portfolio_usd"]
    if start <= 0:
        return 0.0
    return (end - start) / start * 100.0


def run_backtest_sync(cfg: BacktestConfig) -> BacktestResult:
    return asyncio.run(run_backtest(cfg))
