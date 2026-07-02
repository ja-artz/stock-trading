"""Universe discovery via top intraday movers (day gainers)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional

import pandas as pd
import yfinance as yf
from yfinance import EquityQuery

from intraday_momentum.data.store import BarStore
from intraday_momentum.settings import StrategyConfig, UniverseOverrides, load_universe_overrides


@dataclass
class UniverseResult:
    tickers: List[str]
    warnings: List[str] = field(default_factory=list)
    source: str = "day_gainers"
    total_screened: int = 0
    mover_returns: dict[str, float] = field(default_factory=dict)


def is_halted(_ticker: str, _as_of=None) -> bool:
    return False


def _universe_cfg(strategy: StrategyConfig) -> dict:
    return strategy.universe or {}


def _quote_passes_filters(quote: dict, strategy: StrategyConfig) -> bool:
    cfg = _universe_cfg(strategy)
    if quote.get("quoteType") != "EQUITY":
        return False

    symbol = str(quote.get("symbol", "")).upper()
    if not symbol or len(symbol) > 6:
        return False
    if any(ch in symbol for ch in ("-", ".", "^")):
        return False

    price = quote.get("regularMarketPrice") or quote.get("intradayprice")
    if price is None or price < float(cfg.get("min_price", 5)):
        return False

    cap = quote.get("marketCap")
    if cap is not None:
        if cap < float(cfg.get("min_market_cap", 0)):
            return False
        if cap > float(cfg.get("max_market_cap", float("inf"))):
            return False

    avg_vol = quote.get("averageDailyVolume3Month") or 0
    adv_dollar = float(avg_vol) * float(price)
    if adv_dollar < float(cfg.get("min_adv_20d", 0)):
        return False

    pct = quote.get("regularMarketChangePercent")
    if pct is not None and pct < float(cfg.get("min_percent_change", 3)):
        return False

    return True


def _apply_overrides(tickers: List[str], overrides: UniverseOverrides) -> List[str]:
    exclude = {t.upper() for t in overrides.exclude}
    result = [t for t in tickers if t not in exclude]
    for symbol in overrides.include:
        sym = symbol.upper()
        if sym not in result:
            result.insert(0, sym)
    return result


def _fetch_live_day_gainers(strategy: StrategyConfig) -> tuple[List[str], dict[str, float], int]:
    """Fetch today's top movers from yfinance (live scan / ingest)."""
    cfg = _universe_cfg(strategy)
    top_n = int(cfg.get("top_n", 50))
    source = str(cfg.get("source", "day_gainers"))

    if source == "day_gainers":
        result = yf.screen("day_gainers", count=min(top_n * 3, 250))
    else:
        query = EquityQuery(
            "and",
            [
                EquityQuery("eq", ["region", "us"]),
                EquityQuery("gte", ["intradayprice", float(cfg.get("min_price", 5))]),
                EquityQuery(
                    "gte",
                    ["intradaymarketcap", float(cfg.get("min_market_cap", 0))],
                ),
                EquityQuery(
                    "gt",
                    ["percentchange", float(cfg.get("min_percent_change", 3))],
                ),
            ],
        )
        result = yf.screen(
            query,
            size=min(top_n * 3, 250),
            sortField="percentchange",
            sortAsc=False,
        )

    quotes = (result or {}).get("quotes") or []
    total = int((result or {}).get("total", len(quotes)) or 0)
    tickers: List[str] = []
    returns: dict[str, float] = {}

    for quote in quotes:
        if not _quote_passes_filters(quote, strategy):
            continue
        symbol = str(quote["symbol"]).upper()
        if symbol in returns:
            continue
        pct = float(quote.get("regularMarketChangePercent") or 0)
        returns[symbol] = pct / 100.0
        tickers.append(symbol)
        if len(tickers) >= top_n:
            break

    return tickers, returns, total


def session_movers_at_scan(
    store: BarStore,
    session_date: date,
    as_of: datetime,
    strategy: StrategyConfig,
) -> UniverseResult:
    """Point-in-time top movers from stored minute bars (backtest)."""
    cfg = _universe_cfg(strategy)
    top_n = int(cfg.get("top_n", 50))
    min_pct = float(cfg.get("min_percent_change", 3)) / 100.0
    as_of_dt = pd.Timestamp(as_of).to_pydatetime()

    ranked: List[tuple[str, float]] = []
    for ticker in store.list_tickers():
        bars = store.read_session(ticker, session_date, as_of=as_of_dt)
        if bars.empty:
            continue
        tz = bars.index.tz
        pit = bars[bars.index <= pd.Timestamp(as_of_dt).tz_convert(tz)]
        if pit.empty:
            continue
        open_px = float(pit["open"].iloc[0])
        if open_px <= 0:
            continue
        last_px = float(pit["close"].iloc[-1])
        move = (last_px - open_px) / open_px
        if move < min_pct:
            continue
        ranked.append((ticker, move))

    ranked.sort(key=lambda x: x[1], reverse=True)
    top = ranked[:top_n]
    tickers = [t for t, _ in top]
    mover_returns = {t: r for t, r in top}

    overrides = load_universe_overrides()
    tickers = _apply_overrides(tickers, overrides)

    return UniverseResult(
        tickers=tickers,
        warnings=[
            "Backtest movers ranked from stored minute bars at scan time (point-in-time).",
            "Only tickers with ingested data are eligible — ingest day gainers daily to grow coverage.",
        ],
        source="session_movers",
        total_screened=len(ranked),
        mover_returns=mover_returns,
    )


def discover_universe(
    strategy: StrategyConfig,
    store: Optional[BarStore] = None,
    *,
    session_date: Optional[date] = None,
    force_refresh: bool = False,
) -> UniverseResult:
    """Discover today's top movers for ingest (live day gainers)."""
    store = store or BarStore()
    overrides = load_universe_overrides()
    as_of = session_date or datetime.now(timezone.utc).date()
    warnings: List[str] = [
        "Universe = top intraday movers via yfinance day_gainers (live, not historical).",
        "Not survivorship-safe in prototype mode.",
    ]

    if not force_refresh:
        cached = store.get_universe_cache(as_of)
        if cached:
            return UniverseResult(
                tickers=_apply_overrides(cached, overrides),
                warnings=warnings + ["Using cached mover snapshot."],
                source="cache",
                total_screened=len(cached),
            )

    tickers, mover_returns, total = _fetch_live_day_gainers(strategy)
    store.save_universe_cache(as_of, tickers)
    tickers = _apply_overrides(tickers, overrides)

    if not tickers:
        warnings.append("No movers passed filters; check strategy.universe settings.")

    return UniverseResult(
        tickers=tickers,
        warnings=warnings,
        source="day_gainers",
        total_screened=total,
        mover_returns={k: mover_returns[k] for k in tickers if k in mover_returns},
    )


def movers_for_scan(
    store: BarStore,
    strategy: StrategyConfig,
    session_date: date,
    as_of: datetime,
    *,
    live: bool = False,
) -> UniverseResult:
    """Movers to evaluate at a scan window — live gainers or PIT session movers."""
    today = datetime.now(timezone.utc).date()
    if live and session_date >= today:
        return discover_universe(strategy, store, session_date=session_date, force_refresh=True)
    return session_movers_at_scan(store, session_date, as_of, strategy)


def build_universe(
    strategy: StrategyConfig,
    store: Optional[BarStore] = None,
    *,
    session_date: Optional[date] = None,
    intersect_stored: bool = False,
    force_refresh: bool = False,
) -> UniverseResult:
    """Resolve mover universe for ingest or reporting."""
    store = store or BarStore()
    result = discover_universe(
        strategy,
        store,
        session_date=session_date,
        force_refresh=force_refresh,
    )

    if intersect_stored:
        stored = set(store.list_tickers())
        filtered = [t for t in result.tickers if t in stored]
        if len(filtered) < len(result.tickers):
            result.warnings.append(
                f"{len(filtered)} of {len(result.tickers)} movers have stored minute bars."
            )
        result.tickers = filtered

    return result
