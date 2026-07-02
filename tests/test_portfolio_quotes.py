"""Tests for fresh option quotes on portfolio NAV refresh."""

from __future__ import annotations

from unittest.mock import patch

from core.pricing import clear_option_chain_cache


@patch("core.portfolio.clear_option_chain_cache", wraps=clear_option_chain_cache)
@patch("core.portfolio.compute_positions_from_ledger", return_value=(1000.0, []))
def test_compute_nav_clears_option_chain_cache(mock_positions, mock_clear):
    from core.portfolio import compute_nav

    compute_nav(1)
    mock_clear.assert_called_once()
