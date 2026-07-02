"""Close or resolve open positions (sell stock, close option, expire worthless)."""

from __future__ import annotations

from typing import Any, Optional

from core.instruments import find_open_position, is_option_instrument_type, normalize_expiry, trade_notional
from core.ledger import log_trade
from core.portfolio import compute_nav
from core.pricing import get_last_price


def close_position(
    portfolio_id: int,
    *,
    ticker: str,
    instrument_type: str,
    resolution: str,
    quantity: Optional[float] = None,
    price: Optional[float] = None,
    strike: Optional[float] = None,
    expiry: Optional[str] = None,
    member_id: Optional[int] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """
    resolution:
      - sell — sell stock or sell-to-close option (price = fill or premium/share)
      - expire_worthless — option expires with $0 recovery
    """
    ticker = ticker.upper().strip()
    inst = instrument_type.lower()
    if inst in ("call", "put"):
        inst = f"{inst}_option"

    nav = compute_nav(portfolio_id)
    pos = find_open_position(
        nav.get("positions") or [],
        ticker,
        inst,
        strike=strike,
        expiry=expiry,
    )
    if not pos:
        return {"ok": False, "reason": f"No open position for {ticker} ({inst})"}

    qty = quantity if quantity is not None else float(pos["quantity"])
    if qty <= 0 or qty > float(pos["quantity"]) + 1e-9:
        return {"ok": False, "reason": f"Invalid quantity (open: {pos['quantity']})"}

    res = resolution.lower().replace("-", "_")
    is_opt = is_option_instrument_type(inst)

    if res == "expire_worthless":
        if not is_opt:
            return {"ok": False, "reason": "expire_worthless applies to options only"}
        fill_price = 0.0
        note_final = note or "Option expired worthless (paper)"
    elif res == "sell":
        if price is not None:
            fill_price = float(price)
        elif is_opt:
            fill_price = float(pos.get("mark_price") or 0)
        else:
            fill_price = get_last_price(ticker) or float(pos.get("mark_price") or 0)
        if fill_price < 0:
            return {"ok": False, "reason": "Price must be non-negative"}
        if is_opt:
            note_final = note or "Sell to close option (paper)"
        else:
            note_final = note or "Sell stock (paper)"
    else:
        return {"ok": False, "reason": f"Unknown resolution '{resolution}'"}

    result = log_trade(
        portfolio_id,
        side="sell",
        ticker=ticker,
        instrument_type=inst,
        quantity=qty,
        price=fill_price,
        strike=pos.get("strike") if strike is None else strike,
        expiry=normalize_expiry(pos.get("expiry") if expiry is None else expiry),
        member_id=member_id,
        note=note_final,
        block_on_violations=False,
    )
    if not result.get("ok"):
        return result

    return {
        "ok": True,
        "ledger_event_id": result.get("ledger_event_id"),
        "resolution": res,
        "quantity": qty,
        "price": fill_price,
        "notional": trade_notional(qty, fill_price, inst),
        "snapshot": result.get("snapshot"),
    }
