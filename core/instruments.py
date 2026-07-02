"""Stock vs option trade economics (premium per share, 100x multiplier)."""

from __future__ import annotations

from typing import Any, List, Optional

OPTION_CONTRACT_MULTIPLIER = 100


def is_option_instrument_type(instrument_type: str) -> bool:
    t = (instrument_type or "stock").lower()
    return t in ("call_option", "put_option", "call", "put", "option")


def normalize_instrument_type(instrument_type: str) -> str:
    t = (instrument_type or "stock").lower()
    if t in ("call", "put"):
        return f"{t}_option"
    return t


def normalize_expiry(expiry: Any) -> Optional[str]:
    if expiry is None:
        return None
    text = str(expiry).strip()
    return text[:10] if len(text) >= 10 else (text or None)


def option_right_from_instrument(instrument_type: str) -> str:
    t = normalize_instrument_type(instrument_type)
    if "put" in t:
        return "put"
    return "call"


def position_key(
    ticker: str,
    instrument_type: str,
    *,
    strike: Any = None,
    expiry: Any = None,
) -> str:
    """Unique holdings key; options include strike and expiry."""
    sym = (ticker or "").upper()
    inst = normalize_instrument_type(instrument_type)
    if is_option_instrument_type(inst):
        strike_s = f"{float(strike):.4f}" if strike is not None else ""
        exp_s = normalize_expiry(expiry) or ""
        return f"{sym}:{inst}:{strike_s}:{exp_s}"
    return f"{sym}:{inst}"


def positions_match(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    require_option_contract: bool = False,
) -> bool:
    """True when two position-like dicts refer to the same open lot."""
    if (a.get("ticker") or "").upper() != (b.get("ticker") or "").upper():
        return False
    if normalize_instrument_type(a.get("instrument_type", "stock")) != normalize_instrument_type(
        b.get("instrument_type", "stock")
    ):
        return False
    inst = normalize_instrument_type(a.get("instrument_type", "stock"))
    if not is_option_instrument_type(inst):
        return True
    exp_a = normalize_expiry(a.get("expiry"))
    exp_b = normalize_expiry(b.get("expiry"))
    if require_option_contract and (not exp_a or a.get("strike") is None):
        return False
    if exp_a and exp_b and exp_a != exp_b:
        return False
    strike_a = a.get("strike")
    strike_b = b.get("strike")
    if strike_a is not None and strike_b is not None:
        try:
            if abs(float(strike_a) - float(strike_b)) > 0.01:
                return False
        except (TypeError, ValueError):
            return False
    elif strike_a is not None or strike_b is not None:
        return False
    return True


def find_open_position(
    positions: List[dict[str, Any]],
    ticker: str,
    instrument_type: str = "stock",
    *,
    strike: Any = None,
    expiry: Any = None,
) -> Optional[dict[str, Any]]:
    probe = {
        "ticker": ticker,
        "instrument_type": instrument_type,
        "strike": strike,
        "expiry": expiry,
    }
    matches = [p for p in positions if positions_match(p, probe)]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    if strike is not None or expiry:
        strict = [
            p
            for p in matches
            if positions_match(p, probe, require_option_contract=True)
        ]
        if len(strict) == 1:
            return strict[0]
    return matches[0]


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
