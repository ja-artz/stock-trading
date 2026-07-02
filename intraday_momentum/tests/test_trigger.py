"""Trigger and gap discipline tests."""

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from intraday_momentum.settings import StrategyConfig, load_strategy
from intraday_momentum.signals.trigger import evaluate_trigger


def _strategy() -> StrategyConfig:
    return load_strategy()


def _bars_with_gap(gap_up: bool = True) -> pd.DataFrame:
    idx = pd.date_range("2026-07-01 09:30", periods=30, freq="1min", tz="America/New_York")
    open_px = 110.0 if gap_up else 100.0
    closes = [open_px + i * 0.05 for i in range(30)]
    return pd.DataFrame(
        {
            "open": [open_px] * 30,
            "high": [c + 0.1 for c in closes],
            "low": [c - 0.1 for c in closes],
            "close": closes,
            "volume": [50000] * 30,
            "prior_close": [100.0] * 30,
        },
        index=idx,
    )


def test_gap_discipline_rejects_front_loaded_move():
    strategy = _strategy()
    bars = _bars_with_gap(gap_up=True)
    as_of = bars.index[10].to_pydatetime()
    store = MagicMock()
    store.prior_session_close.return_value = 100.0
    store.rvol_baseline_volume.return_value = 10000.0
    result = evaluate_trigger("RIVN", bars, as_of, strategy, store, date(2026, 7, 1))
    assert result is None


def test_intraday_developing_move_can_pass():
    strategy = _strategy()
    idx = pd.date_range("2026-07-01 09:30", periods=30, freq="1min", tz="America/New_York")
    closes = [100.0 + i * 0.25 for i in range(30)]
    bars = pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.1 for c in closes],
            "close": closes,
            "volume": [80000] * 30,
        },
        index=idx,
    )
    as_of = bars.index[20].to_pydatetime()
    store = MagicMock()
    store.prior_session_close.return_value = 100.0
    store.rvol_baseline_volume.return_value = 10000.0
    result = evaluate_trigger("RIVN", bars, as_of, strategy, store, date(2026, 7, 1))
    assert result is not None
