"""Daily benchmark closes (yfinance) stored for portfolio comparison."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from core.db import db_session
from core.pricing import get_daily_close_series, get_last_price

# Household-wide symbols; not tied to portfolio_id (multi-portfolio safe).
DEFAULT_BENCHMARK_SYMBOLS: tuple[str, ...] = ("SPY",)


def _market_today() -> date:
    """US/Eastern calendar date for benchmark session labeling."""
    return datetime.now(ZoneInfo("America/New_York")).date()


def _refresh_recent_closes(
    closes: Dict[date, float],
    symbol: str,
    start: date,
    end: date,
) -> Dict[date, float]:
    """Replace stale stored snapshots with recent yfinance daily closes."""
    fetch_end = max(end, _market_today())
    hist_start = max(start, fetch_end - timedelta(days=14))
    hist = get_daily_close_series(symbol.upper(), hist_start, fetch_end)
    for session_day, px in hist.items():
        if session_day >= start:
            closes[session_day] = px
    return hist


def _session_for_live_quote(end: date, hist: Dict[date, float]) -> Optional[date]:
    """
    Session date to stamp with the latest quote.
    Uses US market calendar so live SPY aligns with chart/NAV trading days
    (UTC midnight can roll ahead of the still-open or just-closed US session).
    """
    market_today = _market_today()
    latest_hist = max(hist) if hist else None
    if end >= market_today:
        return market_today
    if latest_hist is not None and end >= latest_hist:
        return latest_hist
    return None


def upsert_benchmark_close(symbol: str, as_of_date: date, close_usd: float) -> None:
    sym = symbol.upper()
    if close_usd <= 0:
        return
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO benchmark_snapshots (symbol, as_of_date, close_usd)
            VALUES (?, ?, ?)
            ON CONFLICT(symbol, as_of_date) DO UPDATE SET close_usd = excluded.close_usd
            """,
            (sym, as_of_date.isoformat(), float(close_usd)),
        )


def snapshot_benchmark_closes(
    as_of: Optional[date] = None,
    symbols: Sequence[str] = DEFAULT_BENCHMARK_SYMBOLS,
) -> List[dict]:
    """Fetch and persist closes for the current US market session (default)."""
    day = as_of or _market_today()
    written: List[dict] = []
    for sym in symbols:
        sym_u = sym.upper()
        live = get_last_price(sym_u)
        if live is not None and live > 0:
            upsert_benchmark_close(sym_u, day, live)
            written.append({"symbol": sym_u, "as_of_date": day.isoformat(), "close_usd": live})
            continue
        series = get_daily_close_series(sym_u, day - timedelta(days=7), day)
        price = series.get(day)
        if price is None or price <= 0:
            continue
        upsert_benchmark_close(sym_u, day, price)
        written.append({"symbol": sym_u, "as_of_date": day.isoformat(), "close_usd": price})
    return written


def ensure_benchmark_history(
    start: date,
    end: date,
    symbols: Sequence[str] = DEFAULT_BENCHMARK_SYMBOLS,
) -> int:
    """Backfill missing benchmark_snapshots rows from yfinance. Returns rows upserted."""
    if start > end:
        return 0
    upserted = 0
    for sym in symbols:
        sym_u = sym.upper()
        with db_session() as conn:
            existing = {
                row["as_of_date"]
                for row in conn.execute(
                    """
                    SELECT as_of_date FROM benchmark_snapshots
                    WHERE symbol = ? AND as_of_date >= ? AND as_of_date <= ?
                    """,
                    (sym_u, start.isoformat(), end.isoformat()),
                ).fetchall()
            }
        series = get_daily_close_series(sym_u, start, end)
        for session_day, close in series.items():
            key = session_day.isoformat()
            if key in existing:
                continue
            upsert_benchmark_close(sym_u, session_day, close)
            upserted += 1
    return upserted


def get_benchmark_closes(
    symbol: str,
    start: date,
    end: date,
) -> Dict[date, float]:
    sym = symbol.upper()
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT as_of_date, close_usd FROM benchmark_snapshots
            WHERE symbol = ? AND as_of_date >= ? AND as_of_date <= ?
            ORDER BY as_of_date
            """,
            (sym, start.isoformat(), end.isoformat()),
        ).fetchall()
    out: Dict[date, float] = {}
    for row in rows:
        out[date.fromisoformat(row["as_of_date"])] = float(row["close_usd"])
    return out


def get_benchmark_closes_with_live(
    symbol: str,
    start: date,
    end: date,
) -> Dict[date, float]:
    """Stored daily closes refreshed from yfinance; current session uses live quote."""
    sym = symbol.upper()
    closes = dict(get_benchmark_closes(sym, start, end))
    hist = _refresh_recent_closes(closes, sym, start, end)
    session = _session_for_live_quote(end, hist)
    if session is not None:
        live = get_last_price(sym)
        if live and live > 0:
            closes[session] = float(live)
    return closes


def get_benchmark_series_normalized(
    symbol: str,
    start: date,
    end: date,
    *,
    ensure_history: bool = True,
) -> List[dict]:
    """Rebased to 100 at first available point in range."""
    if ensure_history:
        ensure_benchmark_history(start - timedelta(days=7), end, (symbol,))
    closes = get_benchmark_closes(symbol, start, end)
    if not closes:
        return []
    first_day = min(closes)
    base = closes[first_day]
    if base <= 0:
        return []
    return [
        {
            "as_of": d.isoformat(),
            "value": round(closes[d] / base * 100.0, 4),
        }
        for d in sorted(closes)
    ]
