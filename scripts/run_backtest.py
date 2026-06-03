#!/usr/bin/env python3
"""
Historical backtest (CLI): weekly news -> analysts -> trader agent -> paper P&L.

Default: 13 weekly runs ending 2026-06-01. All trader plan items are treated as accepted.

  uv run python scripts/run_backtest.py
  uv run python scripts/run_backtest.py --trader-only   # cached analysis only, run trader
  uv run python scripts/run_backtest.py --skip-trader   # cached analysis + plans only

Daily mode (legacy analyst-only signals):

  uv run python scripts/run_backtest.py --daily --persona-direct
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.config import (  # noqa: E402
    DEFAULT_DAYS,
    DEFAULT_END_DATE,
    DEFAULT_HOLD_TRADING_DAYS,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_NEWS_QUERY,
    DEFAULT_PERSONA,
    DEFAULT_RANDOM_SEED,
    DEFAULT_WEEKS,
)
from backtest.runner import BacktestConfig, run_backtest_sync  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Historical backtest (weekly by default)")
    p.add_argument("--end-date", default=DEFAULT_END_DATE)
    p.add_argument("--weeks", type=int, default=DEFAULT_WEEKS, help="Weekly runs (default 13)")
    p.add_argument(
        "--daily",
        action="store_true",
        help="Daily cadence instead of weekly",
    )
    p.add_argument(
        "--persona-direct",
        action="store_true",
        help="With --daily: use moderate persona recs directly (skip trader agent)",
    )
    p.add_argument(
        "--trader-only",
        action="store_true",
        help="Use cached analysis (runs/); only run trader agent + simulation",
    )
    p.add_argument(
        "--skip-trader",
        action="store_true",
        help="Use cached analysis and cached trader plans (plans/); no LLM",
    )
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Calendar days (daily mode)")
    p.add_argument("--max-days", type=int, default=None, help="Cap trading days (daily mode)")
    p.add_argument("--hold-days", type=int, default=DEFAULT_HOLD_TRADING_DAYS)
    p.add_argument("--capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    p.add_argument("--persona", default=DEFAULT_PERSONA, choices=("aggressive", "moderate", "minimal_risk"))
    p.add_argument(
        "--news-query",
        default=DEFAULT_NEWS_QUERY,
        help="Optional Google News search terms (default: empty = general headlines for that day)",
    )
    p.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    p.add_argument("--news-only", action="store_true")
    p.add_argument("--skip-llm", action="store_true")
    p.add_argument("--refresh-news", action="store_true")
    p.add_argument("-o", "--output", metavar="PATH")
    p.add_argument("--json", action="store_true", help="Print JSON to stdout")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = BacktestConfig(
        end_date=date.fromisoformat(args.end_date),
        days=args.days,
        weeks=args.weeks,
        weekly=not args.daily,
        trader_only=args.trader_only,
        skip_trader=args.skip_trader,
        hold_trading_days=args.hold_days,
        initial_capital=args.capital,
        persona=args.persona,
        news_query=args.news_query,
        random_seed=args.seed,
        fetch_news_only=args.news_only,
        skip_llm=args.skip_llm,
        force_refresh_news=args.refresh_news,
        max_days=args.max_days,
        output_path=args.output,
        quiet=args.quiet,
        json_stdout=args.json,
    )
    if not args.quiet and not args.news_only:
        if cfg.trader_only:
            print("Note: --trader-only — loading analysis from cache/runs/, running trader agent.\n")
        elif cfg.skip_trader:
            print("Note: --skip-trader — using cache/runs/ and cache/plans/ only.\n")
        elif not args.skip_llm:
            print(
                f"Note: weekly backtest — {cfg.weeks} runs (news + analysts + trader). "
                "Cache: data/backtest/cache/\n"
            )
    result = run_backtest_sync(cfg)
    if args.json and result.details.get("weekly_portfolio"):
        return
    if args.quiet and result.report_path:
        print(result.report_path)
    elif args.json and result.report_path:
        print(json.dumps(json.loads(Path(result.report_path).read_text()), indent=2))


if __name__ == "__main__":
    main()
