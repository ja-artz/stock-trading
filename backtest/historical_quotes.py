"""Historical price marks for backtest trader prompts and execution."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from backtest.returns import _price_on, fetch_adj_close
from core import store
from core.ticker_names import company_name_for
from validation import collect_tickers_from_stories


def symbols_from_context(stories: List[dict], positions: List[dict]) -> List[str]:
    symbols = collect_tickers_from_stories(stories)
    for p in positions or []:
        t = (p.get("ticker") or "").strip().upper()
        if t:
            symbols.add(t)
    return sorted(symbols)


def quote_bundle_for_date(
    close: pd.DataFrame,
    symbols: Sequence[str],
    as_of: date,
) -> dict[str, Any]:
    as_of_iso = f"{as_of.isoformat()}T16:00:00+00:00"
    quotes: Dict[str, dict[str, Any]] = {}
    for sym in symbols:
        p = _price_on(close, sym.upper(), as_of)
        quotes[sym.upper()] = {
            "price_usd": round(p, 4) if p and p > 0 else None,
            "company_name": company_name_for(sym),
            "available": bool(p and p > 0),
            "as_of_backtest": as_of.isoformat(),
        }
    return {
        "as_of": as_of_iso,
        "source": "yfinance historical close (backtest)",
        "quotes": quotes,
    }


def price_map_from_close(close: pd.DataFrame, day: date) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if close.empty:
        return out
    for col in close.columns:
        p = _price_on(close, str(col), day)
        if p and p > 0:
            out[str(col).upper()] = float(p)
    return out
