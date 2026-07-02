"""SQLite storage with point-in-time read contract."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Generator, Iterable, List, Optional

import pandas as pd

from intraday_momentum.settings import DEFAULT_DB_PATH

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS minute_bars (
    ticker TEXT NOT NULL,
    ts TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (ticker, ts)
);

CREATE INDEX IF NOT EXISTS idx_minute_bars_ticker_ts ON minute_bars(ticker, ts);

CREATE TABLE IF NOT EXISTS ingest_log (
    ticker TEXT NOT NULL,
    session_date TEXT NOT NULL,
    status TEXT NOT NULL,
    bar_count INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT NOT NULL,
    error_msg TEXT,
    PRIMARY KEY (ticker, session_date)
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    config_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    result_json TEXT
);

CREATE TABLE IF NOT EXISTS universe_cache (
    as_of_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    PRIMARY KEY (as_of_date, ticker)
);
"""


class BarStore:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_bars(self, ticker: str, bars: pd.DataFrame) -> int:
        if bars.empty:
            return 0
        rows = []
        for ts, row in bars.iterrows():
            rows.append(
                (
                    ticker.upper(),
                    pd.Timestamp(ts).tz_convert("America/New_York").isoformat(),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row.get("volume", 0.0)),
                )
            )
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO minute_bars (ticker, ts, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, ts) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume
                """,
                rows,
            )
        return len(rows)

    def log_ingest(
        self,
        ticker: str,
        session_date: date,
        status: str,
        bar_count: int,
        error_msg: Optional[str] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_log (ticker, session_date, status, bar_count, ingested_at, error_msg)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, session_date) DO UPDATE SET
                    status=excluded.status,
                    bar_count=excluded.bar_count,
                    ingested_at=excluded.ingested_at,
                    error_msg=excluded.error_msg
                """,
                (
                    ticker.upper(),
                    session_date.isoformat(),
                    status,
                    bar_count,
                    datetime.now(timezone.utc).isoformat(),
                    error_msg,
                ),
            )

    def get_ingest_status(self, ticker: str, session_date: date) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT status FROM ingest_log WHERE ticker=? AND session_date=?",
                (ticker.upper(), session_date.isoformat()),
            ).fetchone()
        return row["status"] if row else None

    def start_ingest_run(self, mode: str) -> str:
        run_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO ingest_runs (run_id, mode, started_at) VALUES (?, ?, ?)",
                (run_id, mode, datetime.now(timezone.utc).isoformat()),
            )
        return run_id

    def finish_ingest_run(self, run_id: str, summary: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE ingest_runs SET finished_at=?, summary_json=? WHERE run_id=?",
                (datetime.now(timezone.utc).isoformat(), json.dumps(summary), run_id),
            )

    def _ts_query_iso(self, dt: datetime) -> str:
        """Match stored bar timezone (America/New_York from yfinance ingest)."""
        return pd.Timestamp(dt).tz_convert("America/New_York").isoformat()

    def read_bars(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        as_of: Optional[datetime] = None,
    ) -> pd.DataFrame:
        start_bound = pd.Timestamp(start).tz_convert("America/New_York")
        end_bound = pd.Timestamp(end).tz_convert("America/New_York")
        effective_end = pd.Timestamp(as_of).tz_convert("America/New_York") if as_of else end_bound
        if effective_end > end_bound:
            effective_end = end_bound
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, open, high, low, close, volume
                FROM minute_bars
                WHERE ticker=? AND ts >= ? AND ts <= ?
                ORDER BY ts
                """,
                (
                    ticker.upper(),
                    start_bound.isoformat(),
                    effective_end.isoformat(),
                ),
            ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame([dict(r) for r in rows])
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts")
        df.index = df.index.tz_convert("America/New_York")
        return df

    def read_session(
        self,
        ticker: str,
        session_date: date,
        as_of: Optional[datetime] = None,
    ) -> pd.DataFrame:
        start = pd.Timestamp(session_date).tz_localize("America/New_York").replace(
            hour=9, minute=30, second=0
        )
        end = pd.Timestamp(session_date).tz_localize("America/New_York").replace(
            hour=16, minute=0, second=0
        )
        effective_end = end
        if as_of is not None:
            effective_end = min(pd.Timestamp(as_of).tz_convert("America/New_York"), end)
        return self.read_bars(
            ticker,
            start.to_pydatetime(),
            end.to_pydatetime(),
            effective_end.to_pydatetime(),
        )

    def stored_session_dates(self, ticker: str) -> List[date]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT date(ts) AS session_date
                FROM minute_bars
                WHERE ticker=?
                ORDER BY session_date
                """,
                (ticker.upper(),),
            ).fetchall()
        return [date.fromisoformat(r["session_date"]) for r in rows]

    def list_tickers(self) -> List[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT DISTINCT ticker FROM minute_bars ORDER BY ticker").fetchall()
        return [r["ticker"] for r in rows]

    def list_sessions(self, start: Optional[date] = None, end: Optional[date] = None) -> List[date]:
        with self.connect() as conn:
            query = "SELECT DISTINCT date(ts) AS session_date FROM minute_bars"
            params: list = []
            clauses = []
            if start:
                clauses.append("date(ts) >= ?")
                params.append(start.isoformat())
            if end:
                clauses.append("date(ts) <= ?")
                params.append(end.isoformat())
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY session_date"
            rows = conn.execute(query, params).fetchall()
        return [date.fromisoformat(r["session_date"]) for r in rows]

    def save_backtest_run(self, config_hash: str, result: dict) -> str:
        run_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO backtest_runs (run_id, config_hash, created_at, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, config_hash, datetime.now(timezone.utc).isoformat(), json.dumps(result)),
            )
        return run_id

    def prior_session_close(self, ticker: str, session_date: date) -> Optional[float]:
        sessions = self.stored_session_dates(ticker)
        prior_dates = [d for d in sessions if d < session_date]
        if not prior_dates:
            return None
        prior = prior_dates[-1]
        bars = self.read_session(ticker, prior)
        if bars.empty:
            return None
        return float(bars["close"].iloc[-1])

    def rvol_baseline_volume(
        self,
        ticker: str,
        session_date: date,
        as_of: datetime,
        lookback_sessions: int = 10,
    ) -> Optional[float]:
        sessions = [d for d in self.stored_session_dates(ticker) if d < session_date]
        if not sessions:
            return None
        sessions = sessions[-lookback_sessions:]
        tod = pd.Timestamp(as_of).tz_convert("America/New_York")
        minute_of_day = tod.hour * 60 + tod.minute
        volumes: List[float] = []
        for sess in sessions:
            bars = self.read_session(ticker, sess, as_of=as_of.replace(
                year=sess.year, month=sess.month, day=sess.day
            ) if as_of.date() == sess else None)
            if bars.empty:
                continue
            bars_et = bars.tz_convert("America/New_York")
            cumvol = bars_et["volume"].cumsum()
            target_idx = None
            for idx, ts in enumerate(bars_et.index):
                mod = ts.hour * 60 + ts.minute
                if mod >= minute_of_day:
                    target_idx = idx
                    break
            if target_idx is not None:
                volumes.append(float(cumvol.iloc[target_idx]))
        if not volumes:
            return None
        return sum(volumes) / len(volumes)

    def save_universe_cache(self, as_of_date: date, tickers: List[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("DELETE FROM universe_cache WHERE as_of_date=?", (as_of_date.isoformat(),))
            conn.executemany(
                "INSERT INTO universe_cache (as_of_date, ticker, discovered_at) VALUES (?, ?, ?)",
                [(as_of_date.isoformat(), t.upper(), now) for t in tickers],
            )

    def get_universe_cache(self, as_of_date: date) -> List[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT ticker FROM universe_cache WHERE as_of_date=? ORDER BY ticker",
                (as_of_date.isoformat(),),
            ).fetchall()
        return [r["ticker"] for r in rows]
