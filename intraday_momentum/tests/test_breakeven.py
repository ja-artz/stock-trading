"""Breakeven win rate sanity check."""

from intraday_momentum.costs.model import CostModel
from intraday_momentum.validation.stats import breakeven_win_rate


def test_breakeven_approx_45_percent():
    model = CostModel(half_spread_bps=5, slippage_bps=5, cost_multiplier=1.0)
    be = breakeven_win_rate(0.03, 0.02, model)
    assert 0.40 <= be <= 0.42
