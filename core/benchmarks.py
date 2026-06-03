"""Daily benchmark closes (yfinance) stored for portfolio comparison."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from core.db import db_session
from core.pricing import close_on_or_before, get_daily_close_series, get_last_price

# Household-wide symbols; not tied to portfolio_id (multi-portfolio safe).
DEFAULT_BENCHMARK_SYMBOLS: tuple[str, ...] = ("SPY",)


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


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
    """Fetch and persist closes for the given calendar day (default today UTC)."""
    day = as_of or _utc_today()
    written: List[dict] = []
    for sym in symbols:
        series = get_daily_close_series(sym, day, day)
        price = close_on_or_before(series, day)
        if price is None and series:
            price = series[max(series)]
        if price is None or price <= 0:
            continue
        upsert_benchmark_close(sym, day, price)
        written.append({"symbol": sym.upper(), "as_of_date": day.isoformat(), "close_usd": price})
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
    """Stored daily closes; today's point uses latest yfinance price when end is today."""
    closes = dict(get_benchmark_closes(symbol, start, end))
    today = _utc_today()
    if end >= today:
        live = get_last_price(symbol.upper())
        if live and live > 0:
            closes[today] = float(live)
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
