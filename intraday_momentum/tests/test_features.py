"""Feature PIT compliance tests."""

from datetime import datetime

import pandas as pd

from intraday_momentum.features.definitions import compute_features, return_since_open


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2026-07-01 09:30", periods=20, freq="1min", tz="America/New_York")
    closes = [100 + i * 0.5 for i in range(20)]
    return pd.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
            "close": closes,
            "volume": [1000] * 20,
        },
        index=idx,
    )


def test_features_use_only_past_data():
    bars = _bars()
    t_early = bars.index[5].to_pydatetime()
    t_late = bars.index[15].to_pydatetime()
    early = return_since_open(bars, t_early)
    late = return_since_open(bars, t_late)
    assert late > early


def test_future_bars_do_not_change_past_features():
    bars = _bars()
    t = bars.index[10].to_pydatetime()
    f1 = compute_features(bars, t, 99.0)
    mutated = bars.copy()
    mutated.loc[mutated.index[15:], "close"] = 999.0
    f2 = compute_features(mutated, t, 99.0)
    assert f1 == f2
