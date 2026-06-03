"""Insights performance and persona analytics (portfolio-scoped)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from core.benchmarks import (
    DEFAULT_BENCHMARK_SYMBOLS,
    ensure_benchmark_history,
    get_benchmark_closes_with_live,
    snapshot_benchmark_closes,
)
from core.db import db_session, row_to_dict
from core.plan_consensus import PERSONA_KEYS, normalize_persona_consensus
from core.portfolio import compute_nav
from core.pricing import close_on_or_before
from core.portfolio_nav_history import daily_nav_for_period

PERSONA_LABELS = {
    "aggressive": "Aggressive",
    "moderate": "Moderate",
    "minimal_risk": "Minimal risk",
}

VALID_PERIODS = frozenset({"7d", "30d", "90d", "ytd", "all"})
# Until this many distinct daily NAV marks exist, chart uses first-NAV day as baseline (not period start).
MIN_NAV_DAYS_FOR_PERIOD_CHART = 7


def parse_period(period: str, *, today: Optional[date] = None) -> Tuple[Optional[date], date]:
    """Return (period_start inclusive, period_end inclusive). start None means all time."""
    end = today or datetime.now(timezone.utc).date()
    p = (period or "30d").lower()
    if p not in VALID_PERIODS:
        p = "30d"
    if p == "all":
        return None, end
    if p == "ytd":
        return date(end.year, 1, 1), end
    days = {"7d": 7, "30d": 30, "90d": 90}[p]
    return end - timedelta(days=days), end


def _parse_logged_day(logged_at: str) -> date:
    raw = logged_at.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        return dt.date()
    except ValueError:
        return date.fromisoformat(raw[:10])


def _in_period(day: date, start: Optional[date], end: date) -> bool:
    if day > end:
        return False
    if start is None:
        return True
    return day >= start


@dataclass
class _OpenLot:
    quantity: float
    entry_price: float
    entry_day: date
    plan_item_id: Optional[int]
    instrument_type: str


def _load_plan_item_meta(plan_item_ids: List[int]) -> Dict[int, dict]:
    if not plan_item_ids:
        return {}
    placeholders = ",".join("?" * len(plan_item_ids))
    with db_session() as conn:
        rows = conn.execute(
            f"""
            SELECT pi.id, pi.persona_consensus, pi.ticker, pi.action,
                   (SELECT d.decision FROM decisions d WHERE d.plan_item_id = pi.id
                    ORDER BY d.decided_at DESC LIMIT 1) AS last_decision
            FROM plan_items pi
            WHERE pi.id IN ({placeholders})
            """,
            plan_item_ids,
        ).fetchall()
    out: Dict[int, dict] = {}
    for row in rows:
        d = row_to_dict(row)
        consensus = d.get("persona_consensus")
        if isinstance(consensus, str):
            try:
                consensus = json.loads(consensus)
            except json.JSONDecodeError:
                consensus = None
        d["persona_consensus"] = normalize_persona_consensus(consensus)
        out[int(d["id"])] = d
    return out


def _personas_matching_stance(consensus: Optional[dict]) -> List[str]:
    c = normalize_persona_consensus(consensus)
    if not c:
        return []
    return [k for k in PERSONA_KEYS if c.get(k)]


def closed_trades_from_ledger(
    portfolio_id: int,
    *,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
) -> List[dict]:
    """FIFO round-trips from ledger sells."""
    end = period_end or datetime.now(timezone.utc).date()
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM ledger_events
            WHERE portfolio_id = ? AND event_type = 'trade'
            ORDER BY logged_at, id
            """,
            (portfolio_id,),
        ).fetchall()

    open_lots: Dict[str, List[_OpenLot]] = defaultdict(list)
    closed: List[dict] = []
    plan_ids: List[int] = []

    for row in rows:
        ev = row_to_dict(row)
        side = (ev.get("side") or "").lower()
        ticker = (ev.get("ticker") or "").upper()
        inst = ev.get("instrument_type") or "stock"
        key = f"{ticker}:{inst}"
        qty = float(ev["quantity"])
        price = float(ev["price"])
        logged_day = _parse_logged_day(ev["logged_at"])
        plan_item_id = ev.get("plan_item_id")
        if plan_item_id:
            plan_ids.append(int(plan_item_id))

        if side == "buy":
            open_lots[key].append(
                _OpenLot(
                    quantity=qty,
                    entry_price=price,
                    entry_day=logged_day,
                    plan_item_id=int(plan_item_id) if plan_item_id else None,
                    instrument_type=inst,
                )
            )
        elif side == "sell":
            remaining = qty
            sell_id = int(ev["id"])
            while remaining > 1e-9 and open_lots[key]:
                lot = open_lots[key][0]
                take = min(lot.quantity, remaining)
                entry_notional = lot.entry_price * take
                exit_notional = price * take
                realized = exit_notional - entry_notional
                pnl_pct = (realized / entry_notional * 100.0) if entry_notional > 0 else 0.0
                hold_days = max(0, (logged_day - lot.entry_day).days)
                if _in_period(logged_day, period_start, end):
                    closed.append(
                        {
                            "id": sell_id,
                            "date": logged_day.isoformat(),
                            "ticker": ticker,
                            "instrument_type": inst,
                            "entry_price": round(lot.entry_price, 4),
                            "exit_price": round(price, 4),
                            "quantity": round(take, 6),
                            "hold_days": hold_days,
                            "realized_pnl": round(realized, 2),
                            "pnl_pct": round(pnl_pct, 2),
                            "plan_item_id": lot.plan_item_id,
                        }
                    )
                lot.quantity -= take
                remaining -= take
                if lot.quantity <= 1e-9:
                    open_lots[key].pop(0)

    meta = _load_plan_item_meta(list(set(plan_ids)))
    for trade in closed:
        pid = trade.pop("plan_item_id", None)
        info = meta.get(pid) if pid else None
        consensus = info.get("persona_consensus") if info else None
        last_decision = (info or {}).get("last_decision")
        trade["followed_rec"] = bool(pid and last_decision == "accepted")
        trade["matched_personas"] = _personas_matching_stance(consensus) if pid else []

    closed.sort(key=lambda t: t["date"], reverse=True)
    return closed


def _daily_nav_by_date(
    portfolio_id: int,
    start: Optional[date],
    end: date,
) -> Dict[date, float]:
    """Daily NAV from holdings marks + snapshots; not only rows in snapshots table."""
    return daily_nav_for_period(portfolio_id, start, end)


def _nav_on_or_before(nav_by_day: Dict[date, float], day: date) -> Optional[float]:
    if not nav_by_day:
        return None
    value: Optional[float] = None
    for session_day in sorted(nav_by_day):
        if session_day <= day:
            value = nav_by_day[session_day]
        else:
            break
    return value


def _nav_points_for_period(portfolio_id: int, start: Optional[date], end: date) -> List[dict]:
    daily = _daily_nav_by_date(portfolio_id, start, end)
    return [{"as_of": d.isoformat(), "nav_usd": v} for d, v in sorted(daily.items())]


def _first_book_nav_day(
    nav_by_day_full: Dict[date, float],
    initial_cash: float,
) -> Optional[date]:
    """First day the book differs from starting cash (invested), not cash-only marks."""
    if not nav_by_day_full:
        return None
    tol = 0.01
    for d in sorted(nav_by_day_full):
        if abs(nav_by_day_full[d] - initial_cash) > tol:
            return d
    return min(nav_by_day_full)


def _resolve_chart_window(
    nav_by_day_full: Dict[date, float],
    period_start: Optional[date],
    period_end: date,
    *,
    initial_cash: float,
) -> Tuple[Optional[date], date, str, int, Optional[date]]:
    """
    Returns (chart_start, chart_end, chart_mode, nav_day_count, first_nav_day).
    chart_mode: since_first_nav | period | empty
    """
    if not nav_by_day_full:
        return period_start, period_end, "empty", 0, None

    first_nav = _first_book_nav_day(nav_by_day_full, initial_cash)
    if first_nav is None:
        return period_start, period_end, "empty", 0, None

    nav_from_book = {d: v for d, v in nav_by_day_full.items() if d >= first_nav}
    nav_day_count = len(nav_from_book)

    if nav_day_count < MIN_NAV_DAYS_FOR_PERIOD_CHART:
        return first_nav, period_end, "since_first_nav", nav_day_count, first_nav

    chart_start = period_start if period_start is not None else first_nav
    if chart_start < first_nav:
        chart_start = first_nav
    return chart_start, period_end, "period", nav_day_count, first_nav


def _filter_nav_by_range(
    nav_by_day: Dict[date, float],
    start: Optional[date],
    end: date,
) -> Dict[date, float]:
    return {
        d: v
        for d, v in nav_by_day.items()
        if d <= end and (start is None or d >= start)
    }


def _spy_return_breakdown(spy_closes: Dict[date, float], end: date) -> dict[str, Optional[float]]:
    """Session-based SPY moves (daily close), separate from period-start chart baseline."""
    days = sorted(d for d in spy_closes if d <= end)
    out: dict[str, Optional[float]] = {
        "since_prev_close_pct": None,
        "last_2_sessions_pct": None,
    }
    if len(days) < 2:
        return out
    latest = days[-1]
    prev = days[-2]
    p0, p1 = spy_closes.get(prev), spy_closes.get(latest)
    if p0 and p1 and p0 > 0:
        out["since_prev_close_pct"] = round((p1 / p0 - 1.0) * 100.0, 2)
    if len(days) >= 3:
        d0 = days[-3]
        p_start = spy_closes.get(d0)
        if p_start and p1 and p_start > 0:
            out["last_2_sessions_pct"] = round((p1 / p_start - 1.0) * 100.0, 2)
    return out


def _merge_chart_series(
    nav_by_day: Dict[date, float],
    spy_closes: Dict[date, float],
    *,
    period_start: Optional[date],
    period_end: date,
) -> Tuple[List[dict], bool]:
    """
    Cumulative % return from period start (0% baseline), Monarch-style.
    Uses benchmark trading days; portfolio NAV is forward-filled between mark days.
    """
    if not nav_by_day and not spy_closes:
        return [], False

    chart_days = sorted(set(spy_closes.keys()) | set(nav_by_day.keys()))
    chart_days = [d for d in chart_days if d <= period_end and (period_start is None or d >= period_start)]
    plottable_days = [d for d in chart_days if _nav_on_or_before(nav_by_day, d) is not None]
    if not plottable_days:
        return [], False

    first_day = plottable_days[0]
    base_nav = _nav_on_or_before(nav_by_day, first_day)
    if base_nav is None or base_nav <= 0:
        earliest = min(nav_by_day) if nav_by_day else None
        base_nav = nav_by_day.get(earliest) if earliest else None
    if base_nav is None or base_nav <= 0:
        return [], False

    spy_base = close_on_or_before(spy_closes, first_day) if spy_closes else None
    has_spy = spy_base is not None and spy_base > 0

    chart: List[dict] = []
    for d in plottable_days:
        nav = _nav_on_or_before(nav_by_day, d)
        if nav is None:
            continue
        label = d.isoformat()
        portfolio_pct = round((nav / base_nav - 1.0) * 100.0, 4)
        point: dict = {"label": label, "portfolio": portfolio_pct}
        if has_spy and spy_base:
            spy_px = close_on_or_before(spy_closes, d)
            if spy_px:
                point["spy"] = round((spy_px / spy_base - 1.0) * 100.0, 4)
        chart.append(point)
    return chart, has_spy


def build_performance_insights(portfolio_id: int, period: str = "30d") -> dict[str, Any]:
    period_start, period_end = parse_period(period)
    snapshot_benchmark_closes()

    with db_session() as conn:
        port = conn.execute(
            "SELECT initial_cash FROM portfolios WHERE id = ?", (portfolio_id,)
        ).fetchone()
    initial_cash = float(port["initial_cash"]) if port else 1000.0

    nav_full = _daily_nav_by_date(portfolio_id, None, period_end)
    chart_start, chart_end, chart_mode, nav_day_count, first_nav_day = _resolve_chart_window(
        nav_full, period_start, period_end, initial_cash=initial_cash
    )

    history_fetch_start = chart_start or first_nav_day or (period_end - timedelta(days=30))
    ensure_benchmark_history(history_fetch_start - timedelta(days=7), period_end)

    nav_by_day = _filter_nav_by_range(nav_full, chart_start, chart_end)
    nav_points = [{"as_of": d.isoformat(), "nav_usd": v} for d, v in sorted(nav_by_day.items())]
    spy_start = chart_start or first_nav_day or (period_end - timedelta(days=30))
    sym = DEFAULT_BENCHMARK_SYMBOLS[0]
    spy_closes = get_benchmark_closes_with_live(sym, spy_start, period_end)
    chart, benchmarks_available = _merge_chart_series(
        nav_by_day,
        spy_closes,
        period_start=chart_start,
        period_end=chart_end,
    )
    spy_breakdown = _spy_return_breakdown(spy_closes, period_end)
    chart_first_day = chart[0]["label"] if chart else None
    chart_spy_period_pct = chart[-1].get("spy") if chart else None

    metrics_start = chart_start if chart_mode == "since_first_nav" else period_start
    closed = closed_trades_from_ledger(
        portfolio_id, period_start=metrics_start, period_end=period_end
    )

    total_return_pct: Optional[float] = None
    total_return_usd: Optional[float] = None
    vs_spy_pct: Optional[float] = None
    if len(nav_points) >= 1:
        first_nav = nav_points[0]["nav_usd"]
        last_nav = nav_points[-1]["nav_usd"]
        if first_nav > 0:
            total_return_pct = round((last_nav / first_nav - 1) * 100, 2)
            total_return_usd = round(last_nav - first_nav, 2)
        if benchmarks_available and spy_closes and chart_spy_period_pct is not None:
            spy_ret = chart_spy_period_pct
            if total_return_pct is not None:
                vs_spy_pct = round(total_return_pct - spy_ret, 2)

    wins = sum(1 for t in closed if t["realized_pnl"] > 0)
    losses = sum(1 for t in closed if t["realized_pnl"] <= 0)
    win_rate_pct = round(wins / len(closed) * 100, 1) if closed else None
    avg_hold = round(sum(t["hold_days"] for t in closed) / len(closed), 1) if closed else None

    return {
        "portfolio_id": portfolio_id,
        "period": period,
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat(),
        "initial_cash": initial_cash,
        "chart": chart,
        "benchmarks_available": benchmarks_available,
        "benchmark_symbol": DEFAULT_BENCHMARK_SYMBOLS[0],
        "chart_baseline_date": chart_first_day,
        "chart_mode": chart_mode,
        "first_nav_date": first_nav_day.isoformat() if first_nav_day else None,
        "nav_history_days": nav_day_count,
        "chart_effective_start": chart_start.isoformat() if chart_start else None,
        "days_until_period_chart": max(0, MIN_NAV_DAYS_FOR_PERIOD_CHART - nav_day_count),
        "summary": {
            "total_return_pct": total_return_pct,
            "total_return_usd": total_return_usd,
            "vs_spy_pct": vs_spy_pct,
            "spy_period_return_pct": chart_spy_period_pct,
            "spy_since_prev_close_pct": spy_breakdown.get("since_prev_close_pct"),
            "spy_last_2_sessions_pct": spy_breakdown.get("last_2_sessions_pct"),
            "win_rate_pct": win_rate_pct,
            "wins": wins,
            "losses": losses,
            "avg_hold_days": avg_hold,
            "closed_trade_count": len(closed),
        },
        "closed_trades": closed,
    }


def build_persona_insights(portfolio_id: int, period: str = "30d") -> dict[str, Any]:
    period_start, period_end = parse_period(period)
    closed = closed_trades_from_ledger(
        portfolio_id, period_start=period_start, period_end=period_end
    )

    stats: Dict[str, dict] = {
        k: {"matched_trades": 0, "wins": 0, "return_pcts": [], "best": None}
        for k in PERSONA_KEYS
    }

    for trade in closed:
        for persona in trade.get("matched_personas") or []:
            s = stats[persona]
            s["matched_trades"] += 1
            if trade["realized_pnl"] > 0:
                s["wins"] += 1
            s["return_pcts"].append(trade["pnl_pct"])
            label = f"{trade['ticker']} {trade['pnl_pct']:+.1f}%"
            if s["best"] is None or trade["pnl_pct"] > s["best"][1]:
                s["best"] = (label, trade["pnl_pct"])

    stance_counts: Dict[str, int] = {k: 0 for k in PERSONA_KEYS}
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT pi.persona_consensus, wp.plan_at
            FROM plan_items pi
            JOIN weekly_plans wp ON wp.id = pi.weekly_plan_id
            WHERE wp.portfolio_id = ?
            """,
            (portfolio_id,),
        ).fetchall()
    for row in rows:
        plan_day = _parse_logged_day(row["plan_at"])
        if not _in_period(plan_day, period_start, period_end):
            continue
        raw = row["persona_consensus"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = None
        for persona in _personas_matching_stance(raw):
            stance_counts[persona] += 1

    personas_out: List[dict] = []
    for key in PERSONA_KEYS:
        s = stats[key]
        n = s["matched_trades"]
        rets = s["return_pcts"]
        personas_out.append(
            {
                "persona": key,
                "label": PERSONA_LABELS.get(key, key),
                "stance_agreements": stance_counts[key],
                "matched_trades": n,
                "win_rate_pct": round(s["wins"] / n * 100, 1) if n else None,
                "avg_return_pct": round(sum(rets) / len(rets), 2) if rets else None,
                "best_trade": s["best"][0] if s["best"] else None,
            }
        )

    return {
        "portfolio_id": portfolio_id,
        "period": period,
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat(),
        "personas": personas_out,
    }
