"""Stock vs option trade economics (premium per share, 100x multiplier)."""

from __future__ import annotations

OPTION_CONTRACT_MULTIPLIER = 100


def is_option_instrument_type(instrument_type: str) -> bool:
    t = (instrument_type or "stock").lower()
    return t in ("call_option", "put_option", "call", "put", "option")


def trade_notional(quantity: float, price: float, instrument_type: str) -> float:
    """Cash impact magnitude for a trade (premium total for options)."""
    base = abs(quantity) * abs(price)
    if is_option_instrument_type(instrument_type):
        return base * OPTION_CONTRACT_MULTIPLIER
    return base


def apply_buy_to_cash(cash: float, quantity: float, price: float, instrument_type: str, fees: float = 0) -> float:
    return cash - trade_notional(quantity, price, instrument_type) - fees


def apply_sell_to_cash(cash: float, quantity: float, price: float, instrument_type: str, fees: float = 0) -> float:
    return cash + trade_notional(quantity, price, instrument_type) - fees
