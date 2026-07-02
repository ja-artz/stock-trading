"""Terminal and JSON reporting."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from intraday_momentum.costs.model import cost_model_from_config
from intraday_momentum.models import DailyResult, DailyVerdict, TradeRecord
from intraday_momentum.settings import StrategyConfig, prototype_warnings
from intraday_momentum.validation.stats import (
    breakeven_win_rate,
    conditional_win_rate,
    daily_win_rate,
    net_expectancy,
)


def _slice_bucket(value: float, edges: List[float], labels: List[str]) -> str:
    for i, edge in enumerate(edges):
        if value < edge:
            return labels[i]
    return labels[-1]


def build_slices(trades: List[TradeRecord]) -> dict:
    if not trades:
        return {}
    gap_buckets = {"low": [], "mid": [], "high": []}
    rvol_buckets = {"low": [], "mid": [], "high": []}
    tod_buckets = {"early": [], "mid": [], "late": []}

    for t in trades:
        gap = t.features.get("gap_pct", 0.0)
        rvol = t.features.get("rvol", 0.0)
        tod = t.features.get("time_of_day", 0.5)
        gap_key = "low" if gap < 0.02 else "mid" if gap < 0.05 else "high"
        rvol_key = "low" if rvol < 2 else "mid" if rvol < 4 else "high"
        tod_key = "early" if tod < 0.33 else "mid" if tod < 0.66 else "late"
        gap_buckets[gap_key].append(t.net_return)
        rvol_buckets[rvol_key].append(t.net_return)
        tod_buckets[tod_key].append(t.net_return)

    def summarize(bucket: dict) -> dict:
        return {
            k: {
                "count": len(v),
                "expectancy": sum(v) / len(v) if v else 0.0,
            }
            for k, v in bucket.items()
        }

    return {
        "gap": summarize(gap_buckets),
        "rvol": summarize(rvol_buckets),
        "time_of_day": summarize(tod_buckets),
    }


def format_daily_line(d: DailyResult) -> str:
    if d.verdict == DailyVerdict.NO_TRADES:
        scans = ", ".join(f"scan_{i+1}" for i in d.scans_run) or "none"
        return f"{d.session_date}  NO_TRADES  (scans: {scans})"

    outcomes = {}
    for t in d.trades:
        outcomes[t.outcome.value] = outcomes.get(t.outcome.value, 0) + 1
    outcome_str = ", ".join(f"{v} {k}" for k, v in outcomes.items())
    scan_note = f"scan_{d.trades[0].scan_index + 1}" if d.trades else ""
    if d.notes == "cap filled":
        scan_note += ": cap filled"
    skipped = f"  [{d.skipped_count} skipped]" if d.skipped_count else ""
    tickers = ", ".join(t.ticker for t in d.trades)
    ticker_note = f" [{tickers}]" if tickers else ""
    return (
        f"{d.session_date}  {d.verdict.value}  {d.net_pnl_pct:+.2%}  "
        f"({len(d.trades)} trades @ {scan_note}: {outcome_str}){ticker_note}{skipped}"
    )


def _trade_to_dict(trade: TradeRecord) -> dict:
    return {
        "ticker": trade.ticker,
        "session_date": trade.session_date.isoformat(),
        "scan": f"scan_{trade.scan_index + 1}",
        "entry_time": trade.t0.isoformat(),
        "entry_px": trade.entry_px,
        "exit_px": trade.exit_px,
        "outcome": trade.outcome.value,
        "net_return": trade.net_return,
        "holding_min": trade.holding_min,
        "features": trade.features,
    }


def build_report(
    strategy: StrategyConfig,
    trades: List[TradeRecord],
    daily_results: List[DailyResult],
    *,
    data_range: Optional[str] = None,
) -> dict:
    cost_model = cost_model_from_config(strategy.costs)
    target = float(strategy.labels.get("target_pct", 0.03))
    stop = float(strategy.labels.get("stop_pct", 0.02))
    be = breakeven_win_rate(target, stop, cost_model)
    cwr = conditional_win_rate(trades)

    trade_dicts = [_trade_to_dict(t) for t in trades]
    traded_tickers = sorted({t.ticker for t in trades})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prototype_warnings": prototype_warnings(strategy),
        "data_range": data_range,
        "trade_count": len(trades),
        "traded_tickers": traded_tickers,
        "trades": trade_dicts,
        "daily_win_rate": daily_win_rate(daily_results),
        "conditional_win_rate": cwr,
        "breakeven_win_rate": be,
        "net_expectancy_per_trade": net_expectancy(trades),
        "slices": build_slices(trades),
        "daily_results": [
            {
                "session_date": d.session_date.isoformat(),
                "verdict": d.verdict.value,
                "net_pnl_pct": d.net_pnl_pct,
                "trade_count": len(d.trades),
                "tickers": [t.ticker for t in d.trades],
                "trades": [_trade_to_dict(t) for t in d.trades],
                "skipped_count": d.skipped_count,
                "scans_run": d.scans_run,
                "scans_skipped": d.scans_skipped,
            }
            for d in daily_results
        ],
    }


def format_report(report: dict, daily_results: List[DailyResult]) -> str:
    lines = [
        "",
        "=" * 60,
        "  PROTOTYPE — not validation-grade",
        "=" * 60,
        "",
    ]
    for w in report.get("prototype_warnings", []):
        lines.append(f"  ! {w}")
    lines.append("")
    if report.get("data_range"):
        lines.append(f"Data range: {report['data_range']}")
    lines.append(f"Trade count:              {report['trade_count']}")
    lines.append(f"Daily win rate:           {report['daily_win_rate']:.1%}")
    lines.append(f"Conditional win rate:     {report['conditional_win_rate']:.1%}")
    lines.append(f"Breakeven win rate:       {report['breakeven_win_rate']:.1%}")
    lines.append(f"Net expectancy/trade:     {report['net_expectancy_per_trade']:+.2%}")
    if report.get("traded_tickers"):
        lines.append(f"Traded tickers:           {', '.join(report['traded_tickers'])}")
    lines.append("")
    lines.append("Daily verdicts:")
    for d in daily_results:
        lines.append(f"  {format_daily_line(d)}")
    lines.append("")
    lines.append("Slices:")
    for name, buckets in report.get("slices", {}).items():
        lines.append(f"  {name}:")
        for bucket, stats in buckets.items():
            lines.append(
                f"    {bucket}: n={stats['count']} expectancy={stats['expectancy']:+.2%}"
            )
    return "\n".join(lines)


def save_report(report: dict, run_id: Optional[str] = None) -> Path:
    out_dir = Path("data/intraday_momentum/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{run_id}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
