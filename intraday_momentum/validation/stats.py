"""Breakeven math and basic metrics."""

from __future__ import annotations

from typing import List

from intraday_momentum.costs.model import CostModel
from intraday_momentum.models import BarrierOutcome, DailyResult, DailyVerdict, TradeRecord


def breakeven_win_rate(target_pct: float, stop_pct: float, cost_model: CostModel) -> float:
    rt = cost_model.round_trip_fraction
    return (stop_pct + rt) / (target_pct + stop_pct + 2 * rt)


def conditional_win_rate(trades: List[TradeRecord]) -> float:
    resolved = [
        t
        for t in trades
        if t.outcome
        in (BarrierOutcome.TARGET, BarrierOutcome.STOP, BarrierOutcome.VELOCITY_EXIT)
    ]
    if not resolved:
        return 0.0
    wins = sum(
        1
        for t in resolved
        if t.outcome == BarrierOutcome.TARGET
        or (t.outcome == BarrierOutcome.VELOCITY_EXIT and t.net_return > 0)
    )
    return wins / len(resolved)


def net_expectancy(trades: List[TradeRecord]) -> float:
    if not trades:
        return 0.0
    return sum(t.net_return for t in trades) / len(trades)


def daily_verdict(trades: List[TradeRecord], flat_epsilon: float = 1e-6) -> DailyVerdict:
    if not trades:
        return DailyVerdict.NO_TRADES
    net = sum(t.net_return for t in trades)
    if net > flat_epsilon:
        return DailyVerdict.WIN
    if net < -flat_epsilon:
        return DailyVerdict.LOSS
    return DailyVerdict.FLAT


def daily_win_rate(daily_results: List[DailyResult]) -> float:
    active = [d for d in daily_results if d.verdict != DailyVerdict.NO_TRADES]
    if not active:
        return 0.0
    wins = sum(1 for d in active if d.verdict == DailyVerdict.WIN)
    return wins / len(active)
