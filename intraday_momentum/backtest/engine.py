"""Scan-window backtest engine."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import List, Optional, Set

import pandas as pd

from intraday_momentum.costs.model import cost_model_from_config
from intraday_momentum.data.store import BarStore
from intraday_momentum.data.universe import build_universe, movers_for_scan
from intraday_momentum.execution.scan import build_scan_plan
from intraday_momentum.labeling.triple_barrier import label_from_session_bars
from intraday_momentum.models import DailyResult, TradeRecord
from intraday_momentum.settings import StrategyConfig
from intraday_momentum.signals.ranking import select_candidates
from intraday_momentum.signals.trigger import evaluate_trigger
from intraday_momentum.validation.stats import daily_verdict


def run_backtest(
    strategy: StrategyConfig,
    store: BarStore,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    session_date: Optional[date] = None,
) -> tuple[List[TradeRecord], List[DailyResult]]:
    if session_date:
        sessions = [session_date]
    else:
        sessions = store.list_sessions(start, end)
    cost_model = cost_model_from_config(strategy.costs)
    target_pct = float(strategy.labels.get("target_pct", 0.03))
    stop_pct = float(strategy.labels.get("stop_pct", 0.02))
    raw_exit_vel = strategy.labels.get("exit_velocity_threshold")
    exit_velocity_threshold = (
        float(raw_exit_vel) if raw_exit_vel is not None else None
    )
    slope_window_min = int(strategy.trigger.get("slope_window_min", 15))

    all_trades: List[TradeRecord] = []
    daily_results: List[DailyResult] = []

    for sess in sessions:
        plan = build_scan_plan(sess, strategy)
        positions_taken = 0
        taken_tickers: Set[str] = set()
        session_trades: List[TradeRecord] = []
        skipped_total = 0
        scans_run: List[int] = []
        scans_skipped: List[int] = []

        for window in plan.windows:
            if positions_taken >= plan.max_positions:
                scans_skipped.append(window.index)
                continue
            if window.scan_time > plan.entry_cutoff:
                scans_skipped.append(window.index)
                continue

            scans_run.append(window.index)
            as_of = window.scan_time
            candidates = []
            cross_returns = []

            as_of_dt = pd.Timestamp(as_of).to_pydatetime()
            mover_result = movers_for_scan(store, strategy, sess, as_of_dt)
            tickers = mover_result.tickers
            cross_returns = list(mover_result.mover_returns.values())

            for ticker in tickers:
                if ticker in taken_tickers:
                    continue
                bars = store.read_session(ticker, sess, as_of=as_of_dt)
                cand = evaluate_trigger(
                    ticker,
                    bars,
                    as_of_dt,
                    strategy,
                    store,
                    sess,
                    cross_returns,
                )
                if cand:
                    cand.scan_index = window.index
                    candidates.append(cand)

            remaining = plan.max_positions - positions_taken
            taken, skipped = select_candidates(candidates, remaining)
            skipped_total += len(skipped)

            for cand in taken:
                full_bars = store.read_session(cand.ticker, sess)
                label = label_from_session_bars(
                    full_bars,
                    cand.t0,
                    cand.entry_px,
                    target_pct,
                    stop_pct,
                    cost_model,
                    exit_velocity_threshold=exit_velocity_threshold,
                    slope_window_min=slope_window_min,
                )
                trade = TradeRecord(
                    ticker=cand.ticker,
                    session_date=sess,
                    t0=cand.t0,
                    entry_px=cand.entry_px,
                    exit_px=label.exit_px,
                    outcome=label.outcome,
                    net_return=label.net_return,
                    holding_min=label.holding_min,
                    scan_index=cand.scan_index,
                    features=cand.features,
                )
                session_trades.append(trade)
                taken_tickers.add(cand.ticker)
                positions_taken += 1

        net_pnl = sum(t.net_return for t in session_trades)
        verdict = daily_verdict(session_trades)
        notes = ""
        if positions_taken >= plan.max_positions and len(scans_skipped) > 0:
            notes = "cap filled"
        daily_results.append(
            DailyResult(
                session_date=sess,
                verdict=verdict,
                net_pnl_pct=net_pnl,
                trades=session_trades,
                skipped_count=skipped_total,
                scans_run=scans_run,
                scans_skipped=scans_skipped,
                notes=notes,
            )
        )
        all_trades.extend(session_trades)

    return all_trades, daily_results


def config_hash(strategy: StrategyConfig) -> str:
    payload = json.dumps(strategy.raw, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
