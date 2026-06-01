"""Live equity quotes for trader-agent sizing (same yfinance source as Portfolio marks)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from core import store
from core.pricing import get_last_price
from core.ticker_names import company_name_for
from validation import collect_tickers_from_stories


def collect_symbols_for_quotes(
    stories: List[dict],
    positions: Optional[List[dict]] = None,
) -> List[str]:
    symbols = collect_tickers_from_stories(stories)
    for p in positions or []:
        t = (p.get("ticker") or "").strip().upper()
        if t:
            symbols.add(t)
    return sorted(symbols)


def fetch_market_quotes(symbols: List[str]) -> dict[str, Any]:
    as_of = store.utc_now_iso()
    quotes: Dict[str, dict[str, Any]] = {}
    for sym in symbols:
        price = get_last_price(sym)
        quotes[sym] = {
            "price_usd": round(price, 4) if price and price > 0 else None,
            "company_name": company_name_for(sym),
            "available": bool(price and price > 0),
        }
    return {
        "as_of": as_of,
        "source": "yfinance (delayed/unofficial — same as Portfolio Value marks)",
        "quotes": quotes,
    }


def quotes_price_map(bundle: dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for sym, row in (bundle.get("quotes") or {}).items():
        p = row.get("price_usd") if isinstance(row, dict) else None
        if p and float(p) > 0:
            out[sym.upper()] = float(p)
    return out


def ensure_quotes_for_tickers(
    bundle: dict[str, Any],
    tickers: List[str],
) -> dict[str, Any]:
    """Add any missing symbols to an existing quote bundle (mutates bundle)."""
    quotes = bundle.setdefault("quotes", {})
    for raw in tickers:
        sym = (raw or "").strip().upper()
        if not sym or sym in quotes:
            continue
        price = get_last_price(sym)
        quotes[sym] = {
            "price_usd": round(price, 4) if price and price > 0 else None,
            "company_name": company_name_for(sym),
            "available": bool(price and price > 0),
        }
    return bundle


def format_quotes_for_prompt(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, indent=2)


def merge_position_marks(
    bundle: dict[str, Any],
    positions: List[dict],
) -> dict[str, Any]:
    """Prefer ledger mark on open positions when quote fetch failed."""
    quotes = bundle.setdefault("quotes", {})
    for p in positions:
        sym = (p.get("ticker") or "").strip().upper()
        if not sym:
            continue
        mark = p.get("mark_price")
        if mark and float(mark) > 0:
            existing = quotes.get(sym) or {}
            if not existing.get("available"):
                quotes[sym] = {
                    "price_usd": round(float(mark), 4),
                    "company_name": existing.get("company_name") or company_name_for(sym),
                    "available": True,
                    "from_portfolio_mark": True,
                }
    return bundle
