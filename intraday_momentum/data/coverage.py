"""Coverage and gap detection for stored minute-bar archive."""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from intraday_momentum.data.store import BarStore
from intraday_momentum.data.universe import build_universe
from intraday_momentum.models import CoverageReport
from intraday_momentum.settings import StrategyConfig, load_strategy


def coverage_summary(
    store: BarStore,
    strategy: Optional[StrategyConfig] = None,
    tickers: Optional[List[str]] = None,
) -> CoverageReport:
    strategy = strategy or load_strategy()
    warnings: List[str] = []

    discovered = build_universe(strategy, store, force_refresh=False)
    stored = build_universe(strategy, store, intersect_stored=True)
    warnings.extend(discovered.warnings)
    warnings.append(
        f"Mover universe: {len(discovered.tickers)} symbols from day_gainers; "
        f"{len(stored.tickers)} have stored minute bars "
        f"({len(store.list_tickers())} total tickers in database)."
    )

    if tickers is None:
        tickers = stored.tickers or store.list_tickers()

    summaries = []
    for ticker in tickers:
        sessions = store.stored_session_dates(ticker)
        if not sessions:
            summaries.append(
                {
                    "ticker": ticker,
                    "first_session": None,
                    "last_session": None,
                    "session_count": 0,
                    "missing_days": [],
                }
            )
            continue

        first_session = sessions[0]
        last_session = sessions[-1]
        expected = pd.bdate_range(first_session, last_session)
        expected_dates = {d.date() for d in expected}
        actual_dates = set(sessions)
        missing = sorted(expected_dates - actual_dates)

        if missing:
            warnings.append(f"{ticker}: {len(missing)} missing session(s) in stored range.")

        summaries.append(
            {
                "ticker": ticker,
                "first_session": first_session.isoformat(),
                "last_session": last_session.isoformat(),
                "session_count": len(sessions),
                "missing_days": [d.isoformat() for d in missing],
            }
        )

    warnings.append("Gaps may be recoverable via backfill if still inside yfinance's ~7-day window.")
    return CoverageReport(ticker_summaries=summaries, warnings=warnings)


def format_coverage_report(report: CoverageReport) -> str:
    lines = ["=== Coverage Report ==="]
    if report.warnings:
        lines.append("")
        for w in report.warnings[:6]:
            lines.append(f"  - {w}")
        lines.append("")
    for s in report.ticker_summaries[:30]:
        if s["session_count"] == 0:
            lines.append(f"{s['ticker']}: no data")
            continue
        missing = len(s["missing_days"])
        lines.append(
            f"{s['ticker']}: {s['first_session']} .. {s['last_session']} "
            f"({s['session_count']} sessions, {missing} gaps)"
        )
    if len(report.ticker_summaries) > 30:
        lines.append(f"... and {len(report.ticker_summaries) - 30} more tickers")
    return "\n".join(lines)
