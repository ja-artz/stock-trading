"""Post-close incremental ingest job."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from intraday_momentum.data.ingest import format_ingest_summary, run_ingest
from intraday_momentum.models import IngestSummary
from intraday_momentum.settings import DEFAULT_STRATEGY_PATH, load_strategy


def run_daily_ingest(
    *,
    config_path: str = str(DEFAULT_STRATEGY_PATH),
) -> IngestSummary:
    strategy = load_strategy(config_path)
    return run_ingest(mode="daily", strategy=strategy)


def main() -> None:
    summary = run_daily_ingest()
    print(format_ingest_summary(summary))


if __name__ == "__main__":
    main()
