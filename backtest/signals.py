"""Extract trade signals from analysis envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Literal, Optional, Set

import config
from validation import _normalize_equity_ticker, collect_tickers_from_stories

Direction = Literal["long", "short"]


@dataclass(frozen=True)
class TradeSignal:
    signal_date: date
    ticker: str
    direction: Direction
    persona: str
    story_title: str
    instrument_type: str


def _direction_for_instrument(instrument_type: str) -> Optional[Direction]:
    it = (instrument_type or "stock").strip().lower()
    if it in ("stock", "equity", ""):
        return "long"
    if it in ("call_option", "call", "call option"):
        return "long"
    if it in ("put_option", "put", "put option"):
        return "short"
    return None


def extract_recommendations(
    analyses: List[dict],
    signal_date: date,
    *,
    persona: str = "moderate",
    stocks_only: bool = True,
    require_valid_ticker: bool = True,
) -> List[TradeSignal]:
    """Accepted recommendations = all persona recs (stocks-only by default for clean P&L)."""
    out: List[TradeSignal] = []
    seen: Set[tuple[str, str, str]] = set()

    for story in analyses:
        if not isinstance(story, dict):
            continue
        title = (story.get("article_title") or "Unknown")[:120]
        profiles = story.get("analyst_profiles") or {}
        brief = profiles.get(persona) if persona else None
        if not isinstance(brief, dict) or brief.get("error"):
            continue
        for rec in brief.get("recommendations") or []:
            if not isinstance(rec, dict):
                continue
            sym = _normalize_equity_ticker(rec.get("ticker"))
            if not sym:
                continue
            if require_valid_ticker:
                from validation import lookup_ticker_yfinance

                if not lookup_ticker_yfinance(sym).get("valid"):
                    continue
            inst = (rec.get("instrument_type") or "stock").strip().lower()
            if stocks_only and inst not in ("stock", "equity", ""):
                continue
            direction = _direction_for_instrument(inst)
            if not direction:
                continue
            key = (sym, direction, persona)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                TradeSignal(
                    signal_date=signal_date,
                    ticker=sym,
                    direction=direction,
                    persona=persona,
                    story_title=title,
                    instrument_type=inst or "stock",
                )
            )
    return out


def mentioned_tickers(analyses: List[dict]) -> List[str]:
    """All validated tickers referenced in story envelopes (shared context + recs)."""
    symbols = collect_tickers_from_stories(analyses)
    return sorted(symbols)


def extract_all_persona_recommendations(
    analyses: List[dict],
    signal_date: date,
    *,
    stocks_only: bool = True,
) -> List[TradeSignal]:
    """Union of recommendations across all analyst personas."""
    combined: List[TradeSignal] = []
    for pid in config.ANALYST_PROFILES:
        combined.extend(
            extract_recommendations(
                analyses, signal_date, persona=pid, stocks_only=stocks_only
            )
        )
    # Dedupe by ticker+direction keeping first
    seen: Set[tuple[str, str]] = set()
    deduped: List[TradeSignal] = []
    for sig in combined:
        key = (sig.ticker, sig.direction)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(sig)
    return deduped
