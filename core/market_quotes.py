"""Live equity and option quotes for trader-agent sizing."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from core import store
from core.instruments import (
    OPTION_CONTRACT_MULTIPLIER,
    is_option_instrument_type,
    normalize_expiry,
    option_right_from_instrument,
)
from core.pricing import get_last_price, get_option_mark_for_position
from core.ticker_names import company_name_for
from validation import collect_tickers_from_stories


def collect_symbols_for_quotes(
    stories: List[dict],
    positions: Optional[List[dict]] = None,
) -> List[str]:
    symbols = collect_tickers_from_stories(stories)
    for p in positions or []:
        if is_option_instrument_type(p.get("instrument_type", "stock")):
            continue
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


def fetch_option_quotes(positions: Optional[List[dict]] = None) -> dict[str, Any]:
    """Live option premiums for open option positions."""
    as_of = store.utc_now_iso()
    contracts: List[dict[str, Any]] = []
    for p in positions or []:
        if not is_option_instrument_type(p.get("instrument_type", "stock")):
            continue
        qty = float(p.get("quantity") or 0)
        if qty <= 1e-9:
            continue
        mark_info = get_option_mark_for_position(p)
        premium = mark_info.get("premium_per_share")
        fetched_at = mark_info.get("fetched_at")
        cost_basis = float(p.get("cost_basis") or 0)
        market_value = float(p.get("market_value") or 0)
        if premium is None or float(premium) <= 0:
            premium = float(p.get("mark_price") or 0)
            quote_available = False
            fetched_at = None
        else:
            market_value = float(premium) * qty * OPTION_CONTRACT_MULTIPLIER
            quote_available = True
        unrealized = round(market_value - cost_basis, 2)
        pnl_pct = round(unrealized / cost_basis * 100, 2) if cost_basis > 0 else 0.0
        contracts.append(
            {
                "ticker": (p.get("ticker") or "").upper(),
                "instrument_type": p.get("instrument_type"),
                "strike": p.get("strike"),
                "expiry": normalize_expiry(p.get("expiry")),
                "right": option_right_from_instrument(p.get("instrument_type", "stock")),
                "contracts": qty,
                "premium_per_share": round(float(premium), 4) if premium else None,
                "quote_as_of": fetched_at,
                "market_value": round(market_value, 2),
                "cost_basis": round(cost_basis, 2),
                "unrealized_pnl": unrealized,
                "unrealized_pnl_pct": pnl_pct,
                "available": quote_available,
            }
        )
    return {
        "as_of": as_of,
        "source": "yfinance option chain (delayed/unofficial)",
        "contracts": contracts,
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


def format_option_quotes_for_prompt(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, indent=2)


def merge_position_marks(
    bundle: dict[str, Any],
    positions: List[dict],
) -> dict[str, Any]:
    """Prefer ledger mark on open stock positions when quote fetch failed."""
    quotes = bundle.setdefault("quotes", {})
    for p in positions:
        if is_option_instrument_type(p.get("instrument_type", "stock")):
            continue
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
