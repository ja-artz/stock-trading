"""Post-analysis validation: story URL checks and ticker resolution without paid API keys."""

from __future__ import annotations

import contextlib
import io
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
import yfinance as yf

import config

# yfinance prints HTTP errors (e.g. 404 for bad symbols) to stderr; suppress during lookups.
_YF_LOGGERS = ("yfinance", "urllib3", "urllib3.connectionpool")


def _normalize_equity_ticker(raw: Optional[str]) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip().upper()
    if ":" in s:
        s = s.split(":")[-1]
    if re.fullmatch(r"[A-Z]{1,5}", s):
        return s
    return None


def _instrument_candidate_tokens(text: str) -> List[str]:
    """First token in instrument text may be a ticker (e.g. SPY or AAPL)."""
    if not text or not isinstance(text, str):
        return []
    first = text.strip().split()[0] if text.strip() else ""
    t = _normalize_equity_ticker(first)
    return [t] if t else []


def validate_article_url(url: str, timeout: Optional[float] = None) -> Dict[str, Any]:
    """Check that the article URL responds (HEAD, then GET fallback)."""
    timeout = timeout if timeout is not None else getattr(config, "VALIDATION_URL_TIMEOUT", 8)
    result: Dict[str, Any] = {"url": url or "", "ok": False, "status_code": None, "error": None}
    if not url or not url.startswith("http"):
        result["error"] = "missing_or_invalid_url"
        return result
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        result["status_code"] = r.status_code
        if r.status_code < 400:
            result["ok"] = True
            return result
        r2 = requests.get(url, allow_redirects=True, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        result["status_code"] = r2.status_code
        result["ok"] = r2.status_code < 400
        if not result["ok"]:
            result["error"] = f"http_{r2.status_code}"
    except Exception as e:
        result["error"] = str(e)
    return result


def lookup_ticker_yfinance(symbol: str) -> Dict[str, Any]:
    """Resolve a ticker via yfinance (unofficial; no API key)."""
    out: Dict[str, Any] = {"symbol": symbol, "valid": False, "company_name": None, "reason": None}
    old_levels: List[tuple] = []
    for name in _YF_LOGGERS:
        lg = logging.getLogger(name)
        old_levels.append((lg, lg.level))
        lg.setLevel(logging.CRITICAL)
    try:
        # Redirect stderr/stdout so yfinance does not print "HTTP Error 404: Quote not found..."
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            t = yf.Ticker(symbol)
            info = t.info or {}
    except Exception as e:
        out["reason"] = str(e)
        return out
    finally:
        for lg, prev in old_levels:
            lg.setLevel(prev)

    try:
        if not info:
            out["reason"] = "empty_info"
            return out
        name = info.get("longName") or info.get("shortName") or info.get("longBusinessSummary")
        if not name:
            out["reason"] = "missing_name"
            return out
        out["valid"] = True
        out["company_name"] = str(name)[:200]
        out["quote_type"] = info.get("quoteType")
    except Exception as e:
        out["reason"] = str(e)
    return out


def _collect_ticker_paths(envelope: Dict[str, Any]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    sc = envelope.get("shared_context") or {}
    for i, row in enumerate(sc.get("affected_companies") or []):
        t = _normalize_equity_ticker(row.get("ticker"))
        if t:
            pairs.append((f"shared_context.affected_companies[{i}].ticker", t))
    profiles = envelope.get("analyst_profiles") or {}
    for pid, brief in profiles.items():
        if not isinstance(brief, dict) or brief.get("error"):
            continue
        for j, rec in enumerate(brief.get("recommendations") or []):
            t = _normalize_equity_ticker(rec.get("ticker"))
            if t:
                pairs.append((f"analyst_profiles.{pid}.recommendations[{j}].ticker", t))
        for k, pa in enumerate(brief.get("portfolio_actions") or []):
            inst = pa.get("instrument") or ""
            for tok in _instrument_candidate_tokens(inst):
                pairs.append((f"analyst_profiles.{pid}.portfolio_actions[{k}].instrument", tok))
    ie = envelope.get("indirect_effects") or {}
    if ie.get("enabled"):
        for ci, chain in enumerate(ie.get("causal_chains") or []):
            if not isinstance(chain, dict):
                continue
            for ti, row in enumerate(chain.get("tickers") or []):
                t = _normalize_equity_ticker(row.get("ticker") if isinstance(row, dict) else None)
                if t:
                    pairs.append((f"indirect_effects.causal_chains[{ci}].tickers[{ti}].ticker", t))
    return pairs


def collect_tickers_from_envelope(envelope: Dict[str, Any]) -> Set[str]:
    return {sym for _, sym in _collect_ticker_paths(envelope)}


def collect_tickers_from_stories(stories: List[Dict[str, Any]]) -> Set[str]:
    seen: Set[str] = set()
    for story in stories:
        if isinstance(story, dict):
            seen |= collect_tickers_from_envelope(story)
    return seen


def validate_envelope(article: Dict[str, Any], envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    URL check plus unique ticker lookups.
    invalid_tickers: unique symbols that failed (for refinement feedback).
    """
    link = article.get("link") or envelope.get("article_link") or ""
    url_check = validate_article_url(link)
    paths = _collect_ticker_paths(envelope)
    seen: Set[str] = set()
    ticker_checks: List[Dict[str, Any]] = []
    invalid_unique: Dict[str, str] = {}

    for path, sym in paths:
        if sym in seen:
            continue
        seen.add(sym)
        lu = lookup_ticker_yfinance(sym)
        row = {
            "ticker": sym,
            "path": path,
            "valid": lu["valid"],
            "company_name": lu.get("company_name"),
            "reason": lu.get("reason"),
        }
        ticker_checks.append(row)
        if not lu["valid"]:
            invalid_unique[sym] = lu.get("reason") or "invalid"

    invalid_list = [{"ticker": k, "reason": v} for k, v in invalid_unique.items()]
    return {
        "article_url": url_check,
        "ticker_checks": ticker_checks,
        "invalid_tickers": invalid_list,
    }
