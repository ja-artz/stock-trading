"""Tests for option position identity and pricing helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from core.instruments import find_open_position, position_key, positions_match
from core.pricing import clear_option_chain_cache, get_option_last_price


def test_position_key_distinguishes_option_contracts():
    a = position_key("NVDA", "call_option", strike=140, expiry="2026-08-21")
    b = position_key("NVDA", "call_option", strike=150, expiry="2026-08-21")
    c = position_key("NVDA", "call_option", strike=140, expiry="2026-09-18")
    assert a != b
    assert a != c
    assert b != c


def test_stock_position_key_ignores_strike_expiry():
    assert position_key("AAPL", "stock", strike=100, expiry="2026-01-01") == "AAPL:stock"


def test_find_open_position_matches_strike_and_expiry():
    positions = [
        {
            "ticker": "NVDA",
            "instrument_type": "call_option",
            "strike": 140.0,
            "expiry": "2026-08-21",
            "quantity": 2,
        },
        {
            "ticker": "NVDA",
            "instrument_type": "call_option",
            "strike": 150.0,
            "expiry": "2026-08-21",
            "quantity": 1,
        },
    ]
    hit = find_open_position(positions, "NVDA", "call_option", strike=150, expiry="2026-08-21")
    assert hit is not None
    assert hit["strike"] == 150.0


def test_positions_match_requires_strike_when_both_present():
    a = {"ticker": "NVDA", "instrument_type": "call_option", "strike": 140, "expiry": "2026-08-21"}
    b = {"ticker": "NVDA", "instrument_type": "call_option", "strike": 150, "expiry": "2026-08-21"}
    assert not positions_match(a, b)


@patch("core.pricing._load_option_chain")
def test_get_option_last_price_uses_last_price(mock_load):
    clear_option_chain_cache()
    chain = MagicMock(
        calls=pd.DataFrame(
            [{"strike": 140.0, "lastPrice": 12.5, "bid": 12.0, "ask": 13.0}],
        ),
        puts=pd.DataFrame(),
    )
    mock_load.return_value = (chain, "2026-06-30T12:00:00+00:00")
    px = get_option_last_price("NVDA", "2026-08-21", 140.0, "call")
    assert px == 12.5


@patch("core.pricing._load_option_chain")
def test_get_option_last_price_falls_back_to_mid(mock_load):
    clear_option_chain_cache()
    chain = MagicMock(
        calls=pd.DataFrame(
            [{"strike": 140.0, "lastPrice": 0.0, "bid": 10.0, "ask": 12.0}],
        ),
        puts=pd.DataFrame(),
    )
    mock_load.return_value = (chain, "2026-06-30T12:00:00+00:00")
    px = get_option_last_price("NVDA", "2026-08-21", 140.0, "call")
    assert px == 11.0


@patch("core.pricing.get_option_mark")
def test_get_option_mark_for_position(mock_mark):
    mock_mark.return_value = {"premium_per_share": 4.25, "fetched_at": "2026-06-30T12:00:00+00:00"}
    from core.pricing import get_option_mark_for_position

    mark = get_option_mark_for_position(
        {
            "ticker": "AAPL",
            "instrument_type": "put_option",
            "strike": 180,
            "expiry": "2026-07-18",
        }
    )
    assert mark["premium_per_share"] == 4.25
    assert mark["fetched_at"] == "2026-06-30T12:00:00+00:00"
    mock_mark.assert_called_once_with("AAPL", "2026-07-18", 180.0, "put")
