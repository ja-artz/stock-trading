from datetime import date

from core.benchmarks import _session_for_live_quote


def test_session_for_live_quote_uses_us_market_day_when_utc_is_ahead(monkeypatch):
    """UTC can be June 19 while the US session is still June 18."""
    monkeypatch.setattr("core.benchmarks._market_today", lambda: date(2026, 6, 18))
    hist = {date(2026, 6, 16): 600.0, date(2026, 6, 17): 602.0, date(2026, 6, 18): 606.0}
    assert _session_for_live_quote(date(2026, 6, 19), hist) == date(2026, 6, 18)


def test_session_for_live_quote_uses_latest_hist_for_historical_end(monkeypatch):
    monkeypatch.setattr("core.benchmarks._market_today", lambda: date(2026, 6, 18))
    hist = {date(2026, 6, 16): 600.0, date(2026, 6, 17): 602.0}
    assert _session_for_live_quote(date(2026, 6, 17), hist) == date(2026, 6, 17)


def test_session_for_live_quote_none_when_range_before_history(monkeypatch):
    monkeypatch.setattr("core.benchmarks._market_today", lambda: date(2026, 6, 18))
    hist = {date(2026, 6, 16): 600.0, date(2026, 6, 17): 602.0}
    assert _session_for_live_quote(date(2026, 6, 10), hist) is None
