"""Session movers ranking from stored bars."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from intraday_momentum.data.store import BarStore
from intraday_momentum.data.universe import session_movers_at_scan
from intraday_momentum.settings import load_strategy


def _seed_session(store: BarStore, ticker: str, session: date, move: float) -> None:
    idx = pd.date_range(
        f"{session} 09:30",
        periods=20,
        freq="1min",
        tz="America/New_York",
    )
    base = 100.0
    closes = [base * (1 + move * i / 19) for i in range(20)]
    bars = pd.DataFrame(
        {
            "open": [base] * 20,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [100000] * 20,
        },
        index=idx,
    )
    store.upsert_bars(ticker, bars)


def test_session_movers_ranks_by_return(tmp_path):
    db = tmp_path / "t.db"
    store = BarStore(db)
    session = date(2026, 7, 1)
    as_of = datetime(2026, 7, 1, 9, 45, tzinfo=ZoneInfo("America/New_York"))
    _seed_session(store, "LOW", session, 0.02)
    _seed_session(store, "HIGH", session, 0.10)
    _seed_session(store, "MID", session, 0.05)

    strategy = load_strategy()
    strategy.raw["universe"]["top_n"] = 2
    strategy.raw["universe"]["min_percent_change"] = 3

    result = session_movers_at_scan(store, session, as_of, strategy)
    assert result.tickers == ["HIGH", "MID"]
