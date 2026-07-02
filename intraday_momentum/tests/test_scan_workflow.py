"""Scan workflow tests."""

from datetime import date
from pathlib import Path
import tempfile

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from intraday_momentum.backtest.engine import run_backtest
from intraday_momentum.data.store import BarStore
from intraday_momentum.data.universe import UniverseResult
from datetime import datetime
from zoneinfo import ZoneInfo

from intraday_momentum.execution.scan import build_scan_plan, live_scan_allowed
from intraday_momentum.settings import load_strategy


def _make_session_bars(ticker: str, session: date, move_pct: float) -> pd.DataFrame:
    idx = pd.date_range(
        f"{session} 09:30",
        periods=60,
        freq="1min",
        tz="America/Los_Angeles",
    ).tz_convert("America/New_York")
    base = 100.0
    closes = [base * (1 + move_pct * i / 60) for i in range(60)]
    return pd.DataFrame(
        {
            "open": [base] * 60,
            "high": [c * 1.002 for c in closes],
            "low": [c * 0.998 for c in closes],
            "close": closes,
            "volume": [100000] * 60,
        },
        index=idx,
    )


@pytest.fixture
def backtest_env():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        store = BarStore(db)
        strategy = load_strategy()
        strategy.raw["execution"]["max_positions"] = 3
        strategy.raw["execution"]["scan_times"] = ["06:35", "06:50"]
        strategy.raw["trigger"]["move_threshold"] = 0.03
        strategy.raw["trigger"]["rvol_threshold"] = 1.0
        strategy.raw["trigger"]["min_post_open_fraction"] = 0.3
        session = date(2026, 7, 1)
        for ticker in ["AAA", "BBB", "CCC", "DDD"]:
            bars = _make_session_bars(ticker, session, 0.08)
            store.upsert_bars(ticker, bars)
            store.log_ingest(ticker, session, "complete", len(bars))
            prior = date(2026, 6, 30)
            prior_bars = _make_session_bars(ticker, prior, 0.01)
            store.upsert_bars(ticker, prior_bars)
            store.log_ingest(ticker, prior, "complete", len(prior_bars))
        universe = UniverseResult(tickers=["AAA", "BBB", "CCC", "DDD"])
        with patch(
            "intraday_momentum.backtest.engine.movers_for_scan",
            return_value=universe,
        ):
            yield strategy, store, session


def test_scan_plan_respects_max_positions(backtest_env):
    strategy, store, session = backtest_env
    plan = build_scan_plan(session, strategy)
    assert plan.max_positions == 3
    trades, daily = run_backtest(strategy, store, session_date=session)
    assert len(trades) <= 3


def test_live_scan_allowed_before_cutoff():
    strategy = load_strategy()
    plan = build_scan_plan(date(2026, 7, 1), strategy)
    tz = ZoneInfo(strategy.execution.get("timezone", "America/Los_Angeles"))
    before = datetime.combine(date(2026, 7, 1), datetime.strptime("07:00", "%H:%M").time(), tzinfo=tz)
    after = datetime.combine(date(2026, 7, 1), datetime.strptime("08:00", "%H:%M").time(), tzinfo=tz)
    assert live_scan_allowed(plan, before)
    assert not live_scan_allowed(plan, after)


def test_cap_filled_skips_later_scans(backtest_env):
    strategy, store, session = backtest_env
    strategy.raw["execution"]["max_positions"] = 2
    trades, daily = run_backtest(strategy, store, session_date=session)
    assert len(trades) <= 2
    if daily:
        assert daily[0].scans_skipped or len(trades) < 2
