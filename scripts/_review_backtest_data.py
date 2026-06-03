#!/usr/bin/env python3
"""One-off analysis for backtest review questions (cash %, alpha, winning trades by source)."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import cache as bt_cache
from backtest.calendar_util import extended_trading_calendar, next_trading_day, weekly_run_dates
from backtest.config import DEFAULT_WEEKS, DEFAULT_END_DATE, DEFAULT_INITIAL_CAPITAL
from backtest.historical_quotes import price_map_from_close
from backtest.paper_book import PaperBook
from backtest.plan_execution import execute_plan_on_book
from backtest.returns import _price_on, fetch_adj_close
from backtest.weekly_runner import _merge_close, _week_mark_day
from validation import collect_tickers_from_stories

START = date.fromisoformat("2026-03-09")
END = date.fromisoformat("2026-06-01")


def _parse_end() -> date:
    return END


def replay_weekly() -> Tuple[PaperBook, List[date], List[date], object, List[dict]]:
    end = _parse_end()
    run_dates = [d for d in weekly_run_dates(end, DEFAULT_WEEKS) if START <= d <= END]
    if not run_dates:
        run_dates = weekly_run_dates(end, DEFAULT_WEEKS)

    book = PaperBook(cash_usd=DEFAULT_INITIAL_CAPITAL)
    sim_cal = extended_trading_calendar(run_dates[0], run_dates[-1], hold_trading_days=5)
    close = None
    execution_logs: List[dict] = []

    for i, run_day in enumerate(run_dates):
        payload = bt_cache.load_cached_run(run_day)
        if not payload:
            raise RuntimeError(f"missing run cache for {run_day}")
        plan = bt_cache.load_cached_plan(run_day)
        if not plan:
            raise RuntimeError(f"missing plan cache for {run_day}")

        analyses = payload.get("analyses") or []
        symbols = set(collect_tickers_from_stories(analyses))
        for sym in book.positions:
            symbols.add(sym.upper())
        symbols.add("SPY")
        close = _merge_close(close, sorted(symbols), sim_cal[0], sim_cal[-1])

        book.reset_week_counter(run_day)
        trade_day = next_trading_day(run_day, sim_cal) or run_day
        execution_logs.extend(execute_plan_on_book(book, plan, trade_date=trade_day, close=close))

    return book, run_dates, sim_cal, close, execution_logs


def daily_cash_pct_series(run_dates: List[date], sim_cal: List[date]) -> List[Tuple[str, float]]:
    """Replay weekly plans; record cash_pct at each trading day in [START, END]."""
    book = PaperBook(cash_usd=DEFAULT_INITIAL_CAPITAL)
    close = None
    scheduled: List[Tuple[date, date, dict]] = []
    for run_day in run_dates:
        payload = bt_cache.load_cached_run(run_day)
        plan = bt_cache.load_cached_plan(run_day)
        if not payload or not plan:
            raise RuntimeError(f"missing cache for {run_day}")
        analyses = payload.get("analyses") or []
        symbols = set(collect_tickers_from_stories(analyses))
        for sym in book.positions:
            symbols.add(sym.upper())
        symbols.add("SPY")
        close = _merge_close(close, sorted(symbols), sim_cal[0], sim_cal[-1])
        book.reset_week_counter(run_day)
        trade_day = next_trading_day(run_day, sim_cal) or run_day
        scheduled.append((trade_day, run_day, plan))

    rows: List[Tuple[str, float]] = []
    for d in sim_cal:
        if d < START or d > END:
            continue
        for trade_day, run_day, plan in scheduled:
            if trade_day == d:
                execute_plan_on_book(book, plan, trade_date=trade_day, close=close)
        if close is None:
            close = fetch_adj_close(["SPY"], sim_cal[0], sim_cal[-1])
        marks = price_map_from_close(close, d)
        rows.append((d.isoformat(), book.nav_state(marks)["cash_pct"]))
    return rows


@dataclass
class Lot:
    ticker: str
    entry_date: date
    entry_price: float
    qty: float
    run_date: date


def _plan_trade_items(plan: dict) -> List[dict]:
    """Plan line items for replay (stocks only; skips live yfinance validation)."""
    from core.plan_sizing import normalize_plan_item_sizing
    from core.rules import is_option_instrument

    if plan.get("no_changes") and not plan.get("items"):
        return []
    items = []
    for raw in plan.get("items") or []:
        item = normalize_plan_item_sizing(dict(raw))
        action = (item.get("action") or "").lower()
        if action in ("watch", "hold"):
            continue
        ticker = (item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        inst = (item.get("instrument_type") or "stock").lower()
        if is_option_instrument(inst):
            continue
        items.append(item)
    return items


def closed_trades_from_replay(run_dates: List[date], sim_cal: List[date]) -> List[dict]:
    """FIFO round-trips from replayed buys/sells (true closed positions)."""
    book = PaperBook(cash_usd=DEFAULT_INITIAL_CAPITAL)
    close = None
    open_lots: Dict[str, List[Lot]] = defaultdict(list)
    closed: List[dict] = []

    for run_day in run_dates:
        payload = bt_cache.load_cached_run(run_day)
        plan = bt_cache.load_cached_plan(run_day)
        if not plan:
            continue
        analyses = (payload or {}).get("analyses") or []
        symbols = set(collect_tickers_from_stories(analyses))
        for sym in book.positions:
            symbols.add(sym.upper())
        symbols.add("SPY")
        close = _merge_close(close, sorted(symbols), sim_cal[0], sim_cal[-1])
        trade_day = (next_trading_day(run_day, sim_cal) or run_day).isoformat()

        for item in _plan_trade_items(plan):
            sym = item["ticker"].upper()
            action = (item.get("action") or "").lower()
            td = date.fromisoformat(trade_day)
            price = _price_on(close, sym, td)
            if not price or price <= 0:
                continue

            if action == "buy":
                notional = item.get("suggested_notional_usd")
                if notional is None and item.get("pct_nav"):
                    nav = book.mark_nav({sym: price})
                    notional = nav * float(item["pct_nav"]) / 100.0
                if notional is None and item.get("pct_cash"):
                    notional = book.cash_usd * float(item["pct_cash"]) / 100.0
                if notional is None:
                    continue
                qty = float(notional) / price
                if book.apply_buy(sym, float(notional), price):
                    open_lots[sym].append(Lot(sym, td, price, qty, run_day))
            elif action in ("sell", "trim"):
                pos = book.positions.get(sym)
                if not pos or pos["quantity"] <= 1e-9:
                    continue
                held = float(pos["quantity"])
                if item.get("pct_position"):
                    qty = held * min(100.0, float(item["pct_position"])) / 100.0
                elif item.get("suggested_quantity"):
                    qty = min(float(item["suggested_quantity"]), held)
                else:
                    qty = held
                if not book.apply_sell(sym, price, quantity=qty):
                    continue
                remaining = qty
                while remaining > 1e-9 and open_lots[sym]:
                    lot = open_lots[sym][0]
                    take = min(lot.qty, remaining)
                    stock_ret = price / lot.entry_price - 1
                    spy_e = _price_on(close, "SPY", lot.entry_date)
                    spy_x = _price_on(close, "SPY", td)
                    if not spy_e or not spy_x or spy_e <= 0:
                        break
                    spy_ret = spy_x / spy_e - 1
                    alpha = stock_ret - spy_ret
                    closed.append(
                        {
                            "ticker": sym,
                            "entry_date": lot.entry_date.isoformat(),
                            "exit_date": td.isoformat(),
                            "entry_price": round(lot.entry_price, 4),
                            "exit_price": round(price, 4),
                            "return_pct": round(stock_ret * 100, 4),
                            "spy_return_pct": round(spy_ret * 100, 4),
                            "alpha_pct": round(alpha * 100, 4),
                            "win": stock_ret > 0,
                            "run_date": lot.run_date.isoformat(),
                        }
                    )
                    lot.qty -= take
                    remaining -= take
                    if lot.qty <= 1e-9:
                        open_lots[sym].pop(0)

    return closed


def closed_from_hold_period(
    run_dates: List[date], sim_cal: List[date], close, execution_logs: List[dict]
) -> List[dict]:
    """Treat each successful buy as a position closed at week-end mark before next run."""
    closed: List[dict] = []
    buys = [e for e in execution_logs if e.get("ok") and (e.get("action") or "").lower() == "buy"]
    for i, run_day in enumerate(run_dates):
        trade_day = next_trading_day(run_day, sim_cal) or run_day
        mark_day = _week_mark_day(trade_day, i, run_dates, sim_cal)
        week_buys = [b for b in buys if b.get("trade_date") == trade_day.isoformat()]
        for b in week_buys:
            sym = b["ticker"].upper()
            entry_p = float(b["price"])
            exit_p = _price_on(close, sym, mark_day)
            if not exit_p or entry_p <= 0:
                continue
            stock_ret = exit_p / entry_p - 1
            spy_e = _price_on(close, "SPY", trade_day)
            spy_x = _price_on(close, "SPY", mark_day)
            if not spy_e or not spy_x or spy_e <= 0:
                continue
            spy_ret = spy_x / spy_e - 1
            alpha = stock_ret - spy_ret
            closed.append(
                {
                    "ticker": sym,
                    "entry_date": trade_day.isoformat(),
                    "exit_date": mark_day.isoformat(),
                    "entry_price": round(entry_p, 4),
                    "exit_price": round(exit_p, 4),
                    "return_pct": round(stock_ret * 100, 4),
                    "spy_return_pct": round(spy_ret * 100, 4),
                    "alpha_pct": round(alpha * 100, 4),
                    "win": stock_ret > 0,
                    "run_date": run_day.isoformat(),
                }
            )
    return closed


def _story_meta(story: dict, news: List[dict]) -> Dict[str, str]:
    link = story.get("article_link") or ""
    title = story.get("article_title") or ""
    link_to_source = {(a.get("link") or ""): (a.get("source") or "Unknown") for a in news}
    ctx = story.get("shared_context") or {}
    return {
        "source": link_to_source.get(link) or _source_from_title(title, news),
        "retrieval_type": story.get("retrieval_type") or "unknown",
        "story_domain": ctx.get("story_domain") or "unknown",
        "article_title": (title[:72] + "…") if len(title) > 72 else title,
    }


def _story_mentions_ticker(story: dict, ticker: str) -> bool:
    t = ticker.upper()
    ctx = story.get("shared_context") or {}
    for ac in ctx.get("affected_companies") or []:
        if (ac.get("ticker") or "").upper() == t:
            return True
    profiles = story.get("analyst_profiles") or {}
    if isinstance(profiles, dict):
        for prof in profiles.values():
            for rec in prof.get("recommendations") or []:
                if (rec.get("ticker") or "").upper() == t:
                    return True
    blob = json.dumps(story)
    return f'"{t}"' in blob or f'"ticker": "{t}"' in blob


def ticker_to_story_meta(run_day: date, ticker: str) -> Dict[str, str]:
    """Map ticker to originating story: outlet, retrieval_type, story_domain."""
    payload = bt_cache.load_cached_run(run_day) or {}
    news = bt_cache.load_cached_news(run_day) or []
    t = ticker.upper()
    unknown = {
        "source": "Unknown",
        "retrieval_type": "unknown",
        "story_domain": "unknown",
        "article_title": "",
    }

    for story in payload.get("analyses") or []:
        if _story_mentions_ticker(story, t):
            return _story_meta(story, news)
    return unknown


def ticker_to_source(run_day: date, ticker: str) -> str:
    return ticker_to_story_meta(run_day, ticker)["source"]


def _source_from_title(title: Optional[str], articles: List[dict]) -> str:
    if not title:
        return "Unknown"
    for a in articles:
        if a.get("title") == title:
            return a.get("source") or "Unknown"
    return "Unknown"


def main() -> None:
    book, run_dates, sim_cal, close, execution_logs = replay_weekly()

    # Q1: daily cash_pct in window
    snaps = daily_cash_pct_series(run_dates, sim_cal)
    print("=== Q1: date, cash_pct (replay; end-of-day marks, positions carried forward) ===")
    print("Note: portfolio_snapshots table does not exist; this replays cached weekly plans.")
    for d, pct in snaps:
        print(f"  {d}  {pct}")

    # Also weekly mark points right after each run's trades
    print("\n=== Q1b: cash_pct at weekly mark (after each run) ===")
    replay_book = PaperBook(cash_usd=DEFAULT_INITIAL_CAPITAL)
    close2 = None
    for i, run_day in enumerate(run_dates):
        payload = bt_cache.load_cached_run(run_day)
        plan = bt_cache.load_cached_plan(run_day)
        analyses = payload.get("analyses") or []
        symbols = set(collect_tickers_from_stories(analyses))
        for sym in replay_book.positions:
            symbols.add(sym.upper())
        symbols.add("SPY")
        close2 = _merge_close(close2, sorted(symbols), sim_cal[0], sim_cal[-1])
        replay_book.reset_week_counter(run_day)
        trade_day = next_trading_day(run_day, sim_cal) or run_day
        execute_plan_on_book(replay_book, plan, trade_date=trade_day, close=close2)
        mark_day = _week_mark_day(trade_day, i, run_dates, sim_cal)
        nav = replay_book.nav_state(price_map_from_close(close2, mark_day))
        print(f"  {mark_day.isoformat()}  {nav['cash_pct']}  (after run {run_day})")

    # Q2: true closed positions (sell/trim round-trips)
    closed = closed_trades_from_replay(run_dates, sim_cal)
    alphas = [c["alpha_pct"] for c in closed if c.get("alpha_pct") is not None]
    print("\n=== Q2: alpha vs SPY on closed positions (sell/trim exit) ===")
    print(f"Closed round-trips: {len(closed)}")
    if alphas:
        avg = sum(alphas) / len(alphas)
        print(f"Average alpha: {avg:+.4f} pp  ({'adding value' if avg > 0 else 'destroying value'})")
        print(f"Positive alpha trades: {sum(1 for a in alphas if a > 0)} / {len(alphas)}")
        for c in closed:
            meta = ticker_to_story_meta(date.fromisoformat(c["run_date"]), c["ticker"])
            c.update(meta)
            print(
                f"  {c['ticker']} {c['entry_date']}->{c['exit_date']} "
                f"ret {c['return_pct']:+.2f}% spy {c['spy_return_pct']:+.2f}% alpha {c['alpha_pct']:+.2f}% | "
                f"{meta['source']} / {meta['retrieval_type']} / {meta['story_domain']}"
            )
    else:
        print("No fully closed round-trips from sell/trim in this window.")

    sells = [e for e in execution_logs if (e.get("action") or "").lower() in ("sell", "trim") and e.get("ok")]
    print(f"Sell/trim executions (execute_plan log): {len(sells)}")

    # Q3: winning trades by source, retrieval_type, story_domain
    wins_by_source: Counter = Counter()
    wins_by_retrieval: Counter = Counter()
    wins_by_domain: Counter = Counter()
    all_by_retrieval: Counter = Counter()
    all_by_domain: Counter = Counter()

    for c in closed:
        meta = ticker_to_story_meta(date.fromisoformat(c["run_date"]), c["ticker"])
        c.update(meta)
        all_by_retrieval[meta["retrieval_type"]] += 1
        all_by_domain[meta["story_domain"]] += 1
        if not c.get("win"):
            continue
        wins_by_source[meta["source"]] += 1
        wins_by_retrieval[meta["retrieval_type"]] += 1
        wins_by_domain[meta["story_domain"]] += 1

    print("\n=== Q3a: winning trades by news source (outlet) ===")
    for src, n in wins_by_source.most_common():
        print(f"  {src}: {n}")

    print("\n=== Q3b: winning trades by retrieval_type ===")
    for rt, n in wins_by_retrieval.most_common():
        print(f"  {rt}: {n}")

    print("\n=== Q3c: winning trades by story_domain ===")
    for dom, n in wins_by_domain.most_common():
        print(f"  {dom}: {n}")

    print("\n=== Q3d: winning trade detail (source | retrieval_type | story_domain) ===")
    for c in closed:
        if not c.get("win"):
            continue
        print(
            f"  {c['ticker']} {c['entry_date']}->{c['exit_date']} ret {c['return_pct']:+.2f}% | "
            f"{c.get('source')} | {c.get('retrieval_type')} | {c.get('story_domain')}"
        )
        if c.get("article_title"):
            print(f"    story: {c['article_title']}")

    print("\n=== Q3e: all closed trades by retrieval_type (wins in parentheses) ===")
    win_counts_ret = Counter(
        c["retrieval_type"] for c in closed if c.get("win")
    )
    for rt, n in all_by_retrieval.most_common():
        print(f"  {rt}: {n} closed ({win_counts_ret.get(rt, 0)} wins)")

    print("\n=== Q3f: all closed trades by story_domain (wins in parentheses) ===")
    win_counts_dom = Counter(c["story_domain"] for c in closed if c.get("win"))
    for dom, n in all_by_domain.most_common():
        print(f"  {dom}: {n} closed ({win_counts_dom.get(dom, 0)} wins)")

    # sqlite snapshots if any
    db = ROOT / "data" / "app.db"
    if db.exists():
        con = sqlite3.connect(db)
        try:
            rows = con.execute(
                """
                SELECT as_of,
                       ROUND(cash_usd / NULLIF(nav_usd, 0) * 100, 2) AS cash_pct
                FROM snapshots
                WHERE date(as_of) BETWEEN ? AND ?
                ORDER BY as_of
                """,
                (START.isoformat(), END.isoformat()),
            ).fetchall()
            if rows:
                print("\n=== Live app snapshots table (if seeded during window) ===")
                for r in rows:
                    print(f"  {r[0]}  {r[1]}")
        finally:
            con.close()


if __name__ == "__main__":
    main()
