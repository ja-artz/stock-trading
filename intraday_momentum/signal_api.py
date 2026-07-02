"""Merge interface stub for future integration with main app."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from intraday_momentum.models import Candidate, IntradaySnapshot
from intraday_momentum.settings import StrategyConfig, load_strategy
from intraday_momentum.signals.trigger import evaluate_trigger
from intraday_momentum.data.store import BarStore


@dataclass
class ScanContext:
    scan_index: int
    session_date: object
    positions_taken: int
    max_positions: int


def evaluate(
    snapshot: IntradaySnapshot,
    scan_context: ScanContext,
    strategy: Optional[StrategyConfig] = None,
    store: Optional[BarStore] = None,
) -> Optional[Candidate]:
    """Runs the identical trigger code path used in backtest."""
    if scan_context.positions_taken >= scan_context.max_positions:
        return None
    strategy = strategy or load_strategy()
    store = store or BarStore()
    return evaluate_trigger(
        snapshot.ticker,
        snapshot.bars,
        snapshot.as_of,
        strategy,
        store,
        scan_context.session_date,
    )
