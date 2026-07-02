"""Reporting JSON includes traded tickers."""

from datetime import date, datetime

from intraday_momentum.models import BarrierOutcome, DailyResult, DailyVerdict, TradeRecord
from intraday_momentum.reporting.report import build_report
from intraday_momentum.settings import load_strategy


def _trade(ticker: str, session: date, net: float) -> TradeRecord:
    return TradeRecord(
        ticker=ticker,
        session_date=session,
        t0=datetime(2026, 7, 1, 9, 45),
        entry_px=100.0,
        exit_px=100.0 * (1 + net),
        outcome=BarrierOutcome.TARGET if net > 0 else BarrierOutcome.STOP,
        net_return=net,
        holding_min=30,
        scan_index=0,
        features={"return_since_open": 0.05},
    )


def test_report_includes_traded_tickers():
    strategy = load_strategy()
    trades = [_trade("RIVN", date(2026, 7, 1), 0.02), _trade("PLTR", date(2026, 7, 2), -0.01)]
    daily = [
        DailyResult(date(2026, 7, 1), DailyVerdict.WIN, 0.02, trades=[trades[0]]),
        DailyResult(date(2026, 7, 2), DailyVerdict.LOSS, -0.01, trades=[trades[1]]),
    ]
    report = build_report(strategy, trades, daily)

    assert report["traded_tickers"] == ["PLTR", "RIVN"]
    assert len(report["trades"]) == 2
    assert report["trades"][0]["ticker"] == "RIVN"
    assert report["daily_results"][0]["tickers"] == ["RIVN"]
    assert report["daily_results"][1]["trades"][0]["ticker"] == "PLTR"
