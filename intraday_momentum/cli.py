"""Terminal CLI for intraday momentum research."""

from __future__ import annotations

import argparse
from datetime import date, datetime

from intraday_momentum.backtest.engine import config_hash, run_backtest
from intraday_momentum.costs.model import cost_model_from_config
from intraday_momentum.data.coverage import coverage_summary, format_coverage_report
from intraday_momentum.data.ingest import format_ingest_summary, run_ingest
from intraday_momentum.data.store import BarStore
from intraday_momentum.execution.scan import build_scan_plan, live_scan_allowed
from intraday_momentum.reporting.report import build_report, format_report, format_daily_line, save_report
from intraday_momentum.data.universe import build_universe, discover_universe
from intraday_momentum.settings import DEFAULT_STRATEGY_PATH, load_strategy
from intraday_momentum.signals.ranking import select_candidates
from intraday_momentum.signals.trigger import evaluate_trigger
from intraday_momentum.validation.stats import breakeven_win_rate

import pandas as pd
import yfinance as yf


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def cmd_ingest(args: argparse.Namespace) -> None:
    strategy = load_strategy(args.config)
    mode = "bootstrap" if args.bootstrap else "backfill" if args.date_from else "daily"
    summary = run_ingest(
        mode=mode,
        strategy=strategy,
        from_date=_parse_date(args.date_from) if args.date_from else None,
        to_date=_parse_date(args.date_to) if args.date_to else None,
    )
    print(format_ingest_summary(summary))


def cmd_coverage(args: argparse.Namespace) -> None:
    store = BarStore()
    strategy = load_strategy(args.config)
    report = coverage_summary(store, strategy)
    print(format_coverage_report(report))


def cmd_universe(args: argparse.Namespace) -> None:
    strategy = load_strategy(args.config)
    store = BarStore()
    result = build_universe(strategy, store, force_refresh=args.refresh)
    print(f"=== Top Movers ({result.source}) ===")
    print(f"Movers: {len(result.tickers)} (eligible pool: {result.total_screened})")
    for w in result.warnings:
        print(f"  ! {w}")
    show = result.tickers if args.all else result.tickers[:25]
    for sym in show:
        pct = result.mover_returns.get(sym)
        if pct is not None:
            print(f"  {sym}: {pct:+.1%}")
        else:
            print(f"  {sym}")
    if not args.all and len(result.tickers) > 25:
        print(f"... and {len(result.tickers) - 25} more (use --all)")


def cmd_backtest(args: argparse.Namespace) -> None:
    strategy = load_strategy(args.config)
    if args.cost_multiplier:
        strategy.raw.setdefault("costs", {})["cost_multiplier"] = float(args.cost_multiplier)
    store = BarStore()
    start = _parse_date(args.start) if args.start else None
    end = _parse_date(args.end) if args.end else None

    trades, daily_results = run_backtest(strategy, store, start=start, end=end)
    sessions = store.list_sessions(start, end)
    tickers = store.list_tickers()
    data_range = None
    if sessions:
        data_range = f"{sessions[0]} .. {sessions[-1]} ({len(sessions)} sessions, {len(tickers)} tickers)"

    report = build_report(strategy, trades, daily_results, data_range=data_range)
    print(format_report(report, daily_results))
    path = save_report(report)
    store.save_backtest_run(config_hash(strategy), report)
    print(f"\nReport saved: {path}")


def cmd_daily(args: argparse.Namespace) -> None:
    strategy = load_strategy(args.config)
    store = BarStore()
    session_date = _parse_date(args.date) if args.date else datetime.now().date()
    trades, daily_results = run_backtest(
        strategy, store, session_date=session_date
    )
    if not daily_results:
        print(f"No data for {session_date}")
        return
    d = daily_results[0]
    print(format_daily_line(d))
    cost_model = cost_model_from_config(strategy.costs)
    target = float(strategy.labels.get("target_pct", 0.03))
    stop = float(strategy.labels.get("stop_pct", 0.02))
    be = breakeven_win_rate(target, stop, cost_model)
    if trades:
        from intraday_momentum.validation.stats import conditional_win_rate
        print(f"Conditional win rate (day trades): {conditional_win_rate(trades):.1%}")
    print(f"Breakeven win rate: {be:.1%}")


def cmd_scan(args: argparse.Namespace) -> None:
    strategy = load_strategy(args.config)
    store = BarStore()
    today = datetime.now().date()
    plan = build_scan_plan(today, strategy)
    now = datetime.now(tz=plan.entry_cutoff.tzinfo)
    if not live_scan_allowed(plan, now):
        print(f"Past entry cutoff ({plan.entry_cutoff.isoformat()}). No new entries today.")
        return

    scan_times = ", ".join(strategy.execution.get("scan_times", []))
    print(f"Live scan at {now.isoformat()}  (configured scans: {scan_times})")
    result = discover_universe(strategy, store, force_refresh=True)
    tickers = result.tickers
    print(f"Evaluating {len(tickers)} top movers...")
    candidates = []
    for ticker in tickers:
        try:
            bars = yf.download(ticker, interval="1m", period="1d", progress=False)
            if bars.empty:
                continue
            if isinstance(bars.columns, pd.MultiIndex):
                bars.columns = bars.columns.droplevel(1)
            bars = bars.rename(columns=str.lower)
            bars = bars[["open", "high", "low", "close", "volume"]]
            if bars.index.tz is None:
                bars = bars.tz_localize("UTC")
            bars = bars.tz_convert("America/New_York").between_time("09:30", "16:00")
            cand = evaluate_trigger(
                ticker,
                bars,
                now,
                strategy,
                store,
                today,
            )
            if cand:
                candidates.append(cand)
        except Exception as exc:
            print(f"  {ticker}: error {exc}")

    max_pos = plan.max_positions
    taken, skipped = select_candidates(candidates, max_pos)
    if not taken:
        print("No candidates pass filters.")
        return
    print(f"Top {len(taken)} candidate(s):")
    for c in taken:
        print(
            f"  {c.ticker} @ {c.entry_px:.2f}  "
            f"move={c.features.get('return_since_open', 0):.1%}  "
            f"rvol={c.features.get('rvol', 0):.1f}x"
        )
    if skipped:
        print(f"Skipped {len(skipped)} additional candidate(s).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Intraday momentum research CLI")
    parser.add_argument("--config", default=str(DEFAULT_STRATEGY_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest minute bars")
    ingest.add_argument("--bootstrap", action="store_true")
    ingest.add_argument("--from", dest="date_from")
    ingest.add_argument("--to", dest="date_to")
    ingest.set_defaults(func=cmd_ingest)

    sub.add_parser("coverage", help="Show data coverage").set_defaults(func=cmd_coverage)

    universe_cmd = sub.add_parser("universe", help="Show discovered universe")
    universe_cmd.add_argument("--refresh", action="store_true", help="Bypass cache")
    universe_cmd.add_argument("--all", action="store_true", help="Print all symbols")
    universe_cmd.set_defaults(func=cmd_universe)

    backtest = sub.add_parser("backtest", help="Run backtest over archive")
    backtest.add_argument("--start")
    backtest.add_argument("--end")
    backtest.add_argument("--cost-multiplier", type=float)
    backtest.set_defaults(func=cmd_backtest)

    daily = sub.add_parser("daily", help="Daily verdict for one session")
    daily.add_argument("--date")
    daily.set_defaults(func=cmd_daily)

    sub.add_parser("scan", help="Live scan (anytime before entry cutoff)").set_defaults(func=cmd_scan)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
