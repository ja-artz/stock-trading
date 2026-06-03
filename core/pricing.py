"""Market pricing via yfinance."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Optional


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

