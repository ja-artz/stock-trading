"""Transaction cost model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostModel:
    half_spread_bps: float = 5.0
    slippage_bps: float = 5.0
    cost_multiplier: float = 1.0

    @property
    def one_way_bps(self) -> float:
        return (self.half_spread_bps + self.slippage_bps) * self.cost_multiplier

    @property
    def round_trip_fraction(self) -> float:
        return 2 * self.one_way_bps / 10_000

    def effective_entry_px(self, px: float) -> float:
        return px * (1 + self.one_way_bps / 10_000)

    def effective_exit_px(self, px: float) -> float:
        return px * (1 - self.one_way_bps / 10_000)

    def net_return(self, entry_px: float, exit_px: float) -> float:
        buy_px = self.effective_entry_px(entry_px)
        sell_px = self.effective_exit_px(exit_px)
        return (sell_px - buy_px) / buy_px


def cost_model_from_config(costs: dict) -> CostModel:
    return CostModel(
        half_spread_bps=float(costs.get("half_spread_bps", 5)),
        slippage_bps=float(costs.get("slippage_bps", 5)),
        cost_multiplier=float(costs.get("cost_multiplier", 1.0)),
    )
