"""Resolve US ticker symbols to company names (cached yfinance lookups)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from validation import lookup_ticker_yfinance

_name_cache: Dict[str, Optional[str]] = {}
# Bump when lookup preference changes so stale short names are not reused.
_NAME_CACHE_VERSION = "longname-v1"


def company_name_for(symbol: str) -> Optional[str]:
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    cache_key = f"{_NAME_CACHE_VERSION}:{sym}"
    if cache_key in _name_cache:
        return _name_cache[cache_key]
    lu = lookup_ticker_yfinance(sym)
    name = lu.get("company_name") if lu.get("valid") else None
    _name_cache[cache_key] = name
    return name


def resolve_company_names(symbols: Iterable[str]) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for raw in symbols:
        sym = (raw or "").strip().upper()
        if not sym or sym in out:
            continue
        out[sym] = company_name_for(sym)
    return out


def enrich_rows_with_company_name(
    rows: List[dict],
    *,
    ticker_key: str = "ticker",
) -> List[dict]:
    symbols = {(r.get(ticker_key) or "").strip().upper() for r in rows if r.get(ticker_key)}
    names = resolve_company_names(symbols)
    enriched: List[dict] = []
    for row in rows:
        copy = dict(row)
        sym = (copy.get(ticker_key) or "").strip().upper()
        if sym:
            copy["company_name"] = names.get(sym)
        enriched.append(copy)
    return enriched


def enrich_nav_state(nav_state: dict[str, Any]) -> dict[str, Any]:
    positions = enrich_rows_with_company_name(nav_state.get("positions") or [])
    return {**nav_state, "positions": positions}
