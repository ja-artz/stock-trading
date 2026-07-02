"""Market pricing via yfinance."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from core.instruments import normalize_expiry, option_right_from_instrument

_option_chain_cache: Dict[Tuple[str, str], Optional[dict[str, Any]]] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_last_price(ticker: str) -> Optional[float]:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        info = t.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "lastPrice", None)
        if price is not None:
            return float(price)
        hist = t.history(period="5d")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def _resolve_option_expiration(underlying: str, expiry: str) -> Optional[str]:
    """Map YYYY-MM-DD expiry to yfinance expiration string."""
    import yfinance as yf

    target = normalize_expiry(expiry)
    if not target:
        return None
    try:
        available = list(getattr(yf.Ticker(underlying.upper()), "options", None) or [])
    except Exception:
        return None
    for exp in available:
        if str(exp)[:10] == target:
            return exp
    return None


def _load_option_chain(underlying: str, expiry: str) -> Optional[tuple[Any, str]]:
    sym = underlying.upper()
    exp_key = normalize_expiry(expiry) or ""
    cache_key = (sym, exp_key)
    if cache_key in _option_chain_cache:
        entry = _option_chain_cache[cache_key]
        if entry is None:
            return None
        return entry["chain"], entry["fetched_at"]

    resolved = _resolve_option_expiration(sym, expiry)
    if not resolved:
        _option_chain_cache[cache_key] = None
        return None
    try:
        import yfinance as yf

        chain = yf.Ticker(sym).option_chain(resolved)
        fetched_at = _utc_now_iso()
        _option_chain_cache[cache_key] = {"chain": chain, "fetched_at": fetched_at}
        return chain, fetched_at
    except Exception:
        _option_chain_cache[cache_key] = None
        return None


def _premium_from_chain_row(row: Any) -> Optional[float]:
    try:
        last = row.get("lastPrice")
        if last is not None and float(last) > 0:
            return float(last)
        bid = float(row.get("bid") or 0)
        ask = float(row.get("ask") or 0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        if bid > 0:
            return bid
        if ask > 0:
            return ask
    except (TypeError, ValueError):
        pass
    return None


def get_option_mark(
    underlying: str,
    expiry: str,
    strike: float,
    right: str,
) -> dict[str, Optional[Any]]:
    """Premium per share plus chain fetch timestamp (when a price is found)."""
    loaded = _load_option_chain(underlying, expiry)
    if loaded is None:
        return {"premium_per_share": None, "fetched_at": None}
    chain, fetched_at = loaded
    side = (right or "call").lower()
    df = chain.calls if side == "call" else chain.puts
    if df is None or df.empty:
        return {"premium_per_share": None, "fetched_at": None}
    try:
        strikes = df["strike"].astype(float)
        target = float(strike)
        idx = (strikes - target).abs().idxmin()
        row = df.loc[idx]
        if abs(float(row["strike"]) - target) > 0.01:
            return {"premium_per_share": None, "fetched_at": None}
        premium = _premium_from_chain_row(row)
        if premium is None or premium <= 0:
            return {"premium_per_share": None, "fetched_at": None}
        return {"premium_per_share": premium, "fetched_at": fetched_at}
    except Exception:
        return {"premium_per_share": None, "fetched_at": None}


def get_option_last_price(
    underlying: str,
    expiry: str,
    strike: float,
    right: str,
) -> Optional[float]:
    """Latest option premium per share from yfinance option chain."""
    mark = get_option_mark(underlying, expiry, strike, right)
    premium = mark.get("premium_per_share")
    return float(premium) if premium is not None else None


def get_option_mark_for_position(position: dict[str, Any]) -> dict[str, Optional[Any]]:
    """Quote helper for a portfolio position dict."""
    strike = position.get("strike")
    expiry = position.get("expiry")
    if strike is None or not expiry:
        return {"premium_per_share": None, "fetched_at": None}
    right = option_right_from_instrument(position.get("instrument_type", "stock"))
    return get_option_mark(
        position.get("ticker") or "",
        str(expiry),
        float(strike),
        right,
    )


def get_option_last_price_for_position(position: dict[str, Any]) -> Optional[float]:
    mark = get_option_mark_for_position(position)
    premium = mark.get("premium_per_share")
    return float(premium) if premium is not None else None


def clear_option_chain_cache() -> None:
    _option_chain_cache.clear()


def get_daily_close_series(ticker: str, start: date, end: date) -> Dict[date, float]:
    """Trading-day close prices keyed by session date."""
    sym = ticker.upper()
    try:
        import yfinance as yf

        fetch_start = start - timedelta(days=7)
        fetch_end = end + timedelta(days=1)
        hist = yf.Ticker(sym).history(
            start=fetch_start.isoformat(),
            end=fetch_end.isoformat(),
            auto_adjust=True,
        )
        if hist is None or hist.empty:
            return {}
        out: Dict[date, float] = {}
        for idx, row in hist.iterrows():
            day = idx.date() if hasattr(idx, "date") else idx.to_pydatetime().date()
            close = float(row["Close"])
            if close > 0:
                out[day] = close
        return out
    except Exception:
        return {}


def close_on_or_before(closes: Dict[date, float], day: date) -> Optional[float]:
    """Last available close on or before a calendar day."""
    if not closes:
        return None
    price: Optional[float] = None
    for session_day in sorted(closes):
        if session_day <= day:
            price = closes[session_day]
        else:
            break
    return price

