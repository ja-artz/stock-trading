"""In-memory paper portfolio for backtests (no SQLite ledger)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from core.instruments import apply_buy_to_cash, apply_sell_to_cash, trade_notional
from core.rules import is_option_instrument


@dataclass
class PaperBook:
    cash_usd: float
    positions: Dict[str, dict] = field(default_factory=dict)
    new_positions_this_week: int = 0
    _week_anchor: Optional[date] = None

    def nav_state(self, marks: Dict[str, float]) -> dict:
        positions = []
        invested = 0.0
        for sym, pos in self.positions.items():
            qty = float(pos["quantity"])
            if qty <= 1e-9:
                continue
            mark = marks.get(sym.upper()) or float(pos.get("avg_cost") or 0)
            mv = mark * qty
            invested += mv
            positions.append(
                {
                    "ticker": sym.upper(),
                    "instrument_type": pos.get("instrument_type", "stock"),
                    "quantity": qty,
                    "avg_cost": pos.get("avg_cost"),
                    "mark_price": mark,
                    "market_value": mv,
                }
            )
        nav = self.cash_usd + invested
        cash_pct = (self.cash_usd / nav * 100) if nav > 0 else 100.0
        return {
            "cash_usd": round(self.cash_usd, 2),
            "nav_usd": round(nav, 2),
            "invested_usd": round(invested, 2),
            "cash_pct": round(cash_pct, 2),
            "positions": positions,
        }

    def mark_nav(self, marks: Dict[str, float]) -> float:
        return self.nav_state(marks)["nav_usd"]

    def reset_week_counter(self, week_start: date) -> None:
        if self._week_anchor != week_start:
            self._week_anchor = week_start
            self.new_positions_this_week = 0

    def _get_pos(self, ticker: str) -> dict:
        sym = ticker.upper()
        if sym not in self.positions:
            self.positions[sym] = {
                "quantity": 0.0,
                "avg_cost": 0.0,
                "instrument_type": "stock",
            }
        return self.positions[sym]

    def apply_buy(self, ticker: str, notional_usd: float, price: float, *, inst: str = "stock") -> bool:
        if price <= 0 or notional_usd <= 0:
            return False
        if is_option_instrument(inst):
            return False
        qty = notional_usd / price
        cost = trade_notional(qty, price, inst)
        if cost > self.cash_usd + 1e-6:
            notional_usd = self.cash_usd * 0.99
            if notional_usd <= 0:
                return False
            qty = notional_usd / price
            cost = trade_notional(qty, price, inst)
        sym = ticker.upper()
        pos = self._get_pos(sym)
        if pos["quantity"] <= 1e-9:
            self.new_positions_this_week += 1
        old_qty = pos["quantity"]
        old_cost = pos["avg_cost"] * old_qty
        new_qty = old_qty + qty
        pos["quantity"] = new_qty
        pos["avg_cost"] = (old_cost + cost) / new_qty if new_qty > 0 else 0.0
        pos["instrument_type"] = inst
        self.cash_usd = apply_buy_to_cash(self.cash_usd, qty, price, inst, 0.0)
        return True

    def apply_sell(
        self,
        ticker: str,
        price: float,
        *,
        pct_position: Optional[float] = None,
        quantity: Optional[float] = None,
        inst: str = "stock",
    ) -> bool:
        if price <= 0:
            return False
        sym = ticker.upper()
        pos = self.positions.get(sym)
        if not pos or pos["quantity"] <= 1e-9:
            return False
        held = float(pos["quantity"])
        if quantity is not None and quantity > 0:
            qty = min(quantity, held)
        elif pct_position is not None and pct_position > 0:
            qty = held * min(100.0, pct_position) / 100.0
        else:
            qty = held
        if qty <= 1e-9:
            return False
        self.cash_usd = apply_sell_to_cash(self.cash_usd, qty, price, inst, 0.0)
        pos["quantity"] = held - qty
        if pos["quantity"] <= 1e-9:
            pos["quantity"] = 0.0
            pos["avg_cost"] = 0.0
        return True
