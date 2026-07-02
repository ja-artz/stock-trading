"""Daily verdict logic tests."""

from datetime import date, datetime

from intraday_momentum.models import BarrierOutcome, DailyVerdict, TradeRecord
from intraday_momentum.validation.stats import daily_verdict, daily_win_rate
from intraday_momentum.models import DailyResult


def _trade(net: float) -> TradeRecord:
    return TradeRecord(
        ticker="TEST",
        session_date=date(2026, 7, 1),
        t0=datetime(2026, 7, 1, 9, 35),
        entry_px=100.0,
        exit_px=100.0 * (1 + net),
        outcome=BarrierOutcome.TARGET if net > 0 else BarrierOutcome.STOP,
        net_return=net,
        holding_min=10,
        scan_index=0,
    )


def test_daily_win():
    assert daily_verdict([_trade(0.02), _trade(0.01)]) == DailyVerdict.WIN


def test_daily_loss():
    assert daily_verdict([_trade(0.02), _trade(-0.03)]) == DailyVerdict.LOSS


def test_no_trades():
    assert daily_verdict([]) == DailyVerdict.NO_TRADES


def test_daily_win_rate_excludes_no_trade_days():
    results = [
        DailyResult(date(2026, 7, 1), DailyVerdict.WIN, 0.01, trades=[_trade(0.01)]),
        DailyResult(date(2026, 7, 2), DailyVerdict.LOSS, -0.01, trades=[_trade(-0.01)]),
        DailyResult(date(2026, 7, 3), DailyVerdict.NO_TRADES, 0.0),
    ]
    assert daily_win_rate(results) == 0.5
