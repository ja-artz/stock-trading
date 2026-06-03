"""Build backtest report payload; write JSON and/or print terminal summary."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from backtest.config import RESULTS_DIR
from backtest.returns import PortfolioSimulator


def build_report_payload(
    *,
    cfg: Any,
    calendar: List,
    strategy_sim: PortfolioSimulator,
    strategy_return: float,
    spy_return: Optional[float],
    equal_weight_mentioned_pct: float,
    random_pct: float,
    signals_by_day: Dict,
    mentioned_by_day: Dict,
) -> Dict[str, Any]:
    return {
        "generated_at": datetime.now().isoformat(),
        "config": {
            "end_date": cfg.end_date.isoformat(),
            "days": cfg.days,
            "hold_trading_days": cfg.hold_trading_days,
            "initial_capital": cfg.initial_capital,
            "persona": cfg.persona,
            "news_query": cfg.news_query,
            "random_seed": cfg.random_seed,
        },
        "window": {
            "start": calendar[0].isoformat() if calendar else None,
            "end": calendar[-1].isoformat() if calendar else None,
            "trading_days": len(calendar),
        },
        "returns_pct": {
            "strategy_accepted_recommendations": round(strategy_return, 4),
            "spy_buy_and_hold": round(spy_return, 4) if spy_return is not None else None,
            "equal_weight_mentioned_tickers": round(equal_weight_mentioned_pct, 4),
            "random_same_count": round(random_pct, 4),
        },
        "activity": {
            "total_signals": sum(len(v) for v in signals_by_day.values()),
            "days_with_signals": sum(1 for v in signals_by_day.values() if v),
            "closed_trades": len(strategy_sim.closed),
        },
        "equity_curve": [
            {
                "date": snap.as_of.isoformat(),
                "equity_usd": round(snap.equity_usd, 2),
                "open_trades": snap.open_trades,
            }
            for snap in strategy_sim.equity_history
        ],
        "daily_signals": {
            d.isoformat(): [
                {"ticker": s.ticker, "direction": s.direction, "persona": s.persona}
                for s in sigs
            ]
            for d, sigs in signals_by_day.items()
        },
        "daily_mentioned_tickers": {
            d.isoformat(): tickers for d, tickers in mentioned_by_day.items()
        },
        "closed_trades": [
            {
                "signal_date": t.signal_date.isoformat(),
                "entry_date": t.entry_date.isoformat(),
                "exit_date": t.exit_date.isoformat(),
                "ticker": t.ticker,
                "direction": t.direction,
                "notional_usd": round(t.notional_usd, 2),
                "return_pct": round(t.return_pct * 100, 4),
                "pnl_usd": round(t.pnl_usd, 2),
            }
            for t in strategy_sim.closed
        ],
    }


def format_terminal_summary(payload: Dict[str, Any], cfg: Any) -> str:
    r = payload["returns_pct"]
    a = payload["activity"]
    w = payload["window"]
    lines = [
        "=" * 72,
        "BACKTEST SUMMARY",
        "=" * 72,
        f"Window: {w['start']} to {w['end']} ({w['trading_days']} trading days)",
        f"Persona: {cfg.persona} | Hold: {cfg.hold_trading_days} trading days | Capital: ${cfg.initial_capital:,.0f}",
        "",
        "Total return (%):",
        f"  Strategy (all accepted {cfg.persona} stock recs): {r['strategy_accepted_recommendations']:+.2f}",
        (
            f"  SPY buy-and-hold:                        {r['spy_buy_and_hold']:+.2f}"
            if r["spy_buy_and_hold"] is not None
            else "  SPY buy-and-hold:                        n/a"
        ),
        f"  Equal-weight mentioned tickers:          {r['equal_weight_mentioned_tickers']:+.2f}",
        f"  Random (same # names, seeded):           {r['random_same_count']:+.2f}",
        "",
        f"Signals: {a['total_signals']} across {a['days_with_signals']} days | Closed trades: {a['closed_trades']}",
        "=" * 72,
    ]
    return "\n".join(lines)


def write_report(
    *,
    cfg: Any,
    calendar: List,
    strategy_sim: PortfolioSimulator,
    strategy_return: float,
    spy_return: Optional[float],
    equal_weight_mentioned_pct: float,
    random_pct: float,
    signals_by_day: Dict,
    mentioned_by_day: Dict,
    output_path: Optional[Path] = None,
    terminal: bool = True,
    json_stdout: bool = False,
    stream: TextIO = sys.stdout,
) -> str:
    payload = build_report_payload(
        cfg=cfg,
        calendar=calendar,
        strategy_sim=strategy_sim,
        strategy_return=strategy_return,
        spy_return=spy_return,
        equal_weight_mentioned_pct=equal_weight_mentioned_pct,
        random_pct=random_pct,
        signals_by_day=signals_by_day,
        mentioned_by_day=mentioned_by_day,
    )

    if output_path is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = RESULTS_DIR / f"backtest_{ts}.json"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["report_file"] = str(output_path)

    if json_stdout:
        print(json.dumps(payload, indent=2), file=stream)
    elif terminal:
        print(format_terminal_summary(payload, cfg), file=stream)
        print(f"\nJSON report: {output_path}", file=stream)

    return str(output_path)


def write_weekly_report(
    *,
    cfg: Any,
    run_dates: List,
    weekly_portfolio: List[Dict[str, Any]],
    plans_by_week: Optional[Dict[str, dict]] = None,
    execution_logs: Optional[List[dict]] = None,
    total_return_pct: float = 0.0,
    strategy_sim: Optional[PortfolioSimulator] = None,
    signals_by_run: Optional[Dict] = None,
    exit_overrides: Optional[Dict] = None,
    output_path: Optional[str] = None,
    json_stdout: bool = False,
    terminal: bool = True,
    stream: TextIO = sys.stdout,
) -> str:
    if output_path:
        path = Path(output_path)
    else:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = RESULTS_DIR / f"backtest_weekly_{ts}.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "cadence": "weekly",
        "pipeline": "analysis -> trader_agent -> accepted_plan_items",
        "config": {
            "end_date": cfg.end_date.isoformat(),
            "weeks": cfg.weeks,
            "initial_capital": cfg.initial_capital,
            "trader_only": getattr(cfg, "trader_only", False),
            "skip_trader": getattr(cfg, "skip_trader", False),
        },
        "total_return_pct": round(total_return_pct, 4),
        "weekly_portfolio": weekly_portfolio,
        "run_dates": [d.isoformat() for d in run_dates],
        "trader_plans": plans_by_week or {},
        "execution_logs": execution_logs or [],
    }
    if strategy_sim is not None:
        payload["closed_trades"] = len(strategy_sim.closed)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = ["Weekly portfolio (USD)", "-" * 40]
    for row in weekly_portfolio:
        wk = row.get("week", "?")
        as_of = row.get("as_of", "")
        usd = row.get("portfolio_usd", 0)
        sig = row.get("signals", "")
        extra = f"  ({sig} signals)" if sig != "" else ""
        lines.append(f"  Week {wk:>2}  {as_of}  ${usd:,.2f}{extra}")
    lines.append("-" * 40)
    lines.append(f"Total return: {total_return_pct:+.2f}%")
    lines.append(f"JSON: {path}")

    if json_stdout:
        print(json.dumps(payload, indent=2), file=stream)
    elif terminal:
        print("\n".join(lines), file=stream)

    return str(path)
