"""Look-ahead enforcement tests."""

from datetime import date, datetime
from unittest.mock import MagicMock

import pandas as pd

from intraday_momentum.settings import load_strategy
from intraday_momentum.signals.trigger import evaluate_trigger


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2026-07-01 09:30", periods=40, freq="1min", tz="America/New_York")
    closes = [100.0 + i * 0.2 for i in range(40)]
    return pd.DataFrame(
        {
            "open": [100.0] * 40,
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.1 for c in closes],
            "close": closes,
            "volume": [80000] * 40,
        },
        index=idx,
    )


def test_shuffled_future_data_same_decision():
    strategy = load_strategy()
    bars = _bars()
    as_of = bars.index[15].to_pydatetime()
    store = MagicMock()
    store.prior_session_close.return_value = 100.0
    store.rvol_baseline_volume.return_value = 10000.0

    r1 = evaluate_trigger("TEST", bars, as_of, strategy, store, date(2026, 7, 1))

    shuffled = bars.copy()
    future = shuffled.iloc[16:].sample(frac=1.0)
    shuffled.iloc[16:] = future.values

    r2 = evaluate_trigger("TEST", shuffled, as_of, strategy, store, date(2026, 7, 1))

    if r1 is None:
        assert r2 is None
    else:
        assert r2 is not None
        assert r1.entry_px == r2.entry_px
        assert r1.features == r2.features
