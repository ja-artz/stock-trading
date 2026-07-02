"""Triple-barrier labeling tests."""

from datetime import datetime

import pandas as pd
import pytest

from intraday_momentum.costs.model import CostModel
from intraday_momentum.labeling.triple_barrier import label_from_session_bars
from intraday_momentum.models import BarrierOutcome


def _make_bars(prices: list[float], start_hour: int = 9, start_min: int = 36) -> pd.DataFrame:
    idx = pd.date_range(
        f"2026-07-01 {start_hour:02d}:{start_min:02d}",
        periods=len(prices),
        freq="1min",
        tz="America/New_York",
    )
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p * 1.001 for p in prices],
            "low": [p * 0.999 for p in prices],
            "close": prices,
            "volume": [1000] * len(prices),
        },
        index=idx,
    )


def test_target_hit():
    prices = [100.0, 100.5, 101.0, 103.5, 104.0]
    bars = _make_bars(prices)
    t0 = bars.index[0].to_pydatetime()
    bars.loc[bars.index[3], "high"] = 104.0
    label = label_from_session_bars(bars, t0, 100.0, 0.03, 0.02, CostModel())
    assert label.outcome == BarrierOutcome.TARGET


def test_stop_hit():
    prices = [100.0, 99.5, 99.0, 97.5, 97.0]
    bars = _make_bars(prices)
    t0 = bars.index[0].to_pydatetime()
    bars.loc[bars.index[3], "low"] = 97.0
    label = label_from_session_bars(bars, t0, 100.0, 0.03, 0.02, CostModel())
    assert label.outcome == BarrierOutcome.STOP


def test_eod_exit():
    prices = [100.0, 100.2, 100.1, 100.3, 100.2]
    bars = _make_bars(prices)
    t0 = bars.index[0].to_pydatetime()
    label = label_from_session_bars(bars, t0, 100.0, 0.03, 0.02, CostModel())
    assert label.outcome == BarrierOutcome.EOD


def test_velocity_exit_on_negative_slope():
    prices = [100.0 + i * 0.05 for i in range(12)]
    prices += [100.6 - i * 0.08 for i in range(1, 25)]
    bars = _make_bars(prices)
    t0 = bars.index[0].to_pydatetime()
    label = label_from_session_bars(
        bars,
        t0,
        100.0,
        0.03,
        0.02,
        CostModel(),
        exit_velocity_threshold=-0.0005,
        slope_window_min=15,
    )
    assert label.outcome == BarrierOutcome.VELOCITY_EXIT
    assert label.net_return < 0


def test_stop_takes_priority_over_velocity_exit_on_same_bar():
    prices = [100.0, 100.0, 100.0, 100.0, 100.0]
    bars = _make_bars(prices)
    t0 = bars.index[0].to_pydatetime()
    bars.loc[bars.index[3], "low"] = 97.0
    label = label_from_session_bars(
        bars,
        t0,
        100.0,
        0.03,
        0.02,
        CostModel(),
        exit_velocity_threshold=-0.0001,
        slope_window_min=15,
    )
    assert label.outcome == BarrierOutcome.STOP
