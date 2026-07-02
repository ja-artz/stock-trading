"""yfinance minute-bar ingestion (bootstrap, daily, backfill)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd
import yfinance as yf

from intraday_momentum.data.store import BarStore
from intraday_momentum.data.universe import build_universe
from intraday_momentum.models import IngestSummary
from intraday_momentum.settings import StrategyConfig, load_strategy

ET = "America/New_York"


def _filter_regular_hours(bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty:
        return bars
    if bars.index.tz is None:
        bars = bars.tz_localize("UTC")
    bars = bars.tz_convert(ET)
    intraday = bars.between_time("09:30", "16:00")
    return intraday


def _split_sessions(bars: pd.DataFrame) -> dict[date, pd.DataFrame]:
    if bars.empty:
        return {}
    bars = bars.copy()
    bars_et = bars.tz_convert(ET)
    sessions: dict[date, pd.DataFrame] = {}
    for session_date, group in bars_et.groupby(bars_et.index.date):
        sessions[session_date] = group
    return sessions


def _fetch_yfinance_1m(ticker: str, period: str = "7d") -> pd.DataFrame:
    df = yf.download(
        ticker,
        interval="1m",
        period=period,
        progress=False,
        auto_adjust=True,
    )
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = df.rename(columns=str.lower)
    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            return pd.DataFrame()
    return _filter_regular_hours(df[required])


def _ingest_ticker_sessions(
    store: BarStore,
    ticker: str,
    target_dates: List[date],
    min_bars: int,
    *,
    force_partial: bool = False,
) -> Tuple[int, int, int, int, List[str]]:
    errors: List[str] = []
    added = skipped = failed = partial = 0

    dates_to_fetch = []
    for session_date in target_dates:
        status = store.get_ingest_status(ticker, session_date)
        if status == "complete" and not force_partial:
            skipped += 1
            continue
        dates_to_fetch.append(session_date)

    if not dates_to_fetch:
        return added, skipped, failed, partial, errors

    try:
        bars = _fetch_yfinance_1m(ticker)
    except Exception as exc:
        errors.append(f"{ticker}: fetch failed: {exc}")
        for session_date in dates_to_fetch:
            store.log_ingest(ticker, session_date, "failed", 0, str(exc))
            failed += 1
        return added, skipped, failed, partial, errors

    sessions = _split_sessions(bars)
    for session_date in dates_to_fetch:
        session_bars = sessions.get(session_date)
        if session_bars is None or session_bars.empty:
            store.log_ingest(ticker, session_date, "failed", 0, "no data in yfinance window")
            failed += 1
            continue
        count = store.upsert_bars(ticker, session_bars)
        if count < min_bars:
            store.log_ingest(ticker, session_date, "partial", count, f"only {count} bars")
            partial += 1
        else:
            store.log_ingest(ticker, session_date, "complete", count)
            added += 1
    return added, skipped, failed, partial, errors


def _target_dates_for_daily(buffer_sessions: int) -> List[date]:
    today = datetime.now().date()
    dates = []
    d = today
    while len(dates) < buffer_sessions + 1:
        if pd.Timestamp(d).weekday() < 5:
            dates.append(d)
        d -= timedelta(days=1)
    return sorted(set(dates))


def _target_dates_bootstrap(window_days: int) -> List[date]:
    end = datetime.now().date()
    start = end - timedelta(days=window_days)
    bdays = pd.bdate_range(start, end)
    return [d.date() for d in bdays]


def _target_dates_range(from_date: date, to_date: date) -> List[date]:
    bdays = pd.bdate_range(from_date, to_date)
    return [d.date() for d in bdays]


def run_ingest(
    *,
    mode: str = "daily",
    strategy: Optional[StrategyConfig] = None,
    store: Optional[BarStore] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    force_refresh_universe: bool = False,
) -> IngestSummary:
    strategy = strategy or load_strategy()
    store = store or BarStore()
    min_bars = int(strategy.ingest.get("min_bars_per_session", 300))

    if mode == "bootstrap":
        target_dates = _target_dates_bootstrap(
            int(strategy.prototype.get("yfinance_rolling_window_days", 7))
        )
        force_refresh_universe = True
    elif mode == "backfill":
        if not from_date or not to_date:
            raise ValueError("backfill mode requires from_date and to_date")
        target_dates = _target_dates_range(from_date, to_date)
    else:
        buffer_sessions = int(strategy.ingest.get("daily_buffer_sessions", 1))
        target_dates = _target_dates_for_daily(buffer_sessions)

    run_id = store.start_ingest_run(mode)
    universe_result = build_universe(strategy, store, force_refresh=force_refresh_universe)
    summary = IngestSummary(mode=mode, tickers_processed=len(universe_result.tickers))

    for ticker in universe_result.tickers:
        added, skipped, failed, partial, errors = _ingest_ticker_sessions(
            store, ticker, target_dates, min_bars
        )
        summary.sessions_added += added
        summary.sessions_skipped += skipped
        summary.sessions_failed += failed
        summary.sessions_partial += partial
        summary.errors.extend(errors)

    store.finish_ingest_run(
        run_id,
        {
            "mode": mode,
            "sessions_added": summary.sessions_added,
            "sessions_skipped": summary.sessions_skipped,
            "sessions_failed": summary.sessions_failed,
            "sessions_partial": summary.sessions_partial,
            "errors": summary.errors,
        },
    )
    return summary


def format_ingest_summary(summary: IngestSummary) -> str:
    lines = [
        f"=== Ingest ({summary.mode}) ===",
        f"Tickers processed: {summary.tickers_processed}",
        f"Sessions added:    {summary.sessions_added}",
        f"Sessions skipped:  {summary.sessions_skipped}",
        f"Sessions partial:  {summary.sessions_partial}",
        f"Sessions failed:   {summary.sessions_failed}",
    ]
    if summary.errors:
        lines.append("Errors:")
        for err in summary.errors[:10]:
            lines.append(f"  - {err}")
    return "\n".join(lines)
