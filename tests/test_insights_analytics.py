"""Tests for insights persona / closed-trade P&L math."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from core.insights_analytics import _OpenLot, closed_trades_from_ledger


def test_closed_option_round_trip_uses_contract_multiplier():
    """Premium per share must not be compared to full contract market value."""
    events = [
        {
            "id": 1,
            "event_type": "trade",
            "side": "buy",
            "ticker": "TLT",
            "instrument_type": "put_option",
            "quantity": 1.0,
            "price": 1.17,
            "fees": 0.06,
            "strike": 90.0,
            "expiry": "2026-09-18",
            "logged_at": "2026-06-26T16:00:00+00:00",
            "plan_item_id": None,
        },
        {
            "id": 2,
            "event_type": "trade",
            "side": "sell",
            "ticker": "TLT",
            "instrument_type": "put_option",
            "quantity": 1.0,
            "price": 1.17,
            "fees": 0.0,
            "strike": 90.0,
            "expiry": "2026-09-18",
            "logged_at": "2026-06-30T16:00:00+00:00",
            "plan_item_id": None,
        },
    ]

    with patch("core.insights_analytics.db_session") as mock_db:
        conn = mock_db.return_value.__enter__.return_value
        conn.execute.return_value.fetchall.return_value = events

        with patch("core.insights_analytics.accepted_plans_by_ticker", return_value={}):
            with patch("core.insights_analytics._load_plan_item_meta", return_value={}):
                closed = closed_trades_from_ledger(1, period_start=date(2026, 6, 1), period_end=date(2026, 6, 30))

    assert len(closed) == 1
    trade = closed[0]
    assert trade["realized_pnl"] == 0.0
    assert trade["pnl_pct"] == 0.0


def test_open_lot_option_fifo_keyed_by_contract():
    """Different strikes must not cross-match in FIFO."""
    from collections import defaultdict

    from core.instruments import position_key

    key_a = position_key("TLT", "put_option", strike=90, expiry="2026-09-18")
    key_b = position_key("TLT", "put_option", strike=95, expiry="2026-09-18")
    assert key_a != key_b

    open_lots = defaultdict(list)
    open_lots[key_a].append(
        _OpenLot(
            quantity=1.0,
            entry_price=1.0,
            entry_day=date(2026, 6, 1),
            plan_item_id=None,
            instrument_type="put_option",
            ledger_event_id=1,
        )
    )
    assert key_b not in open_lots
