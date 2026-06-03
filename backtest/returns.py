"""Price history and P&L for backtest strategies and baselines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Set

import pandas as pd

from backtest.calendar_util import (
    add_trading_days,
    extended_trading_calendar,
    next_trading_day,
    trading_day_on_or_before,
    trading_days_between,
)
from backtest.signals import Direction, TradeSignal


@dataclass
class ClosedTrade:
    signal_date: date
    entry_date: date
    exit_date: date
    ticker: str
    direction: Direction
    notional_usd: float
    return_pct: float
    pnl_usd: float


@dataclass
class DailySnapshot:
    as_of: date
    equity_usd: float
    open_trades: int
    closed_trades_today: int


def fetch_adj_close(
    symbols: Sequence[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Columns = tickers, index = dates (normalized), values = adjusted close."""
    import yfinance as yf

    tickers = sorted({s.upper() for s in symbols if s})
    if not tickers:
        return pd.DataFrame()
    # Buffer for entry/exit around window
    fetch_start = start - timedelta(days=14)
    fetch_end = end + timedelta(days=21)
    raw = yf.download(
        tickers,
        start=fetch_start.isoformat(),
        end=(fetch_end + timedelta(days=1)).isoformat(),
        progress=False,
        auto_adjust=True,
        group_by="column",
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    close = raw["Close"]
    # yfinance returns MultiIndex columns; Close is then a DataFrame, not a Series.
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    else:
        close = close.copy()
        close.columns = [str(c).upper() for c in close.columns]
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    return close.sort_index()


def _price_on(close: pd.DataFrame, ticker: str, day: date) -> Optional[float]:
    if close.empty or ticker not in close.columns:
        return None
    ts = pd.Timestamp(day)
    series = close[ticker].dropna()
    if ts in series.index:
        val = float(series.loc[ts])
        if val > 0:
            return val
    # forward-fill from prior session
    prior = series.loc[:ts]
    if prior.empty:
        return None
    val = float(prior.iloc[-1])
    return val if val > 0 else None


def trade_return_pct(
    close: pd.DataFrame,
    ticker: str,
    direction: Direction,
    entry_date: date,
    exit_date: date,
) -> Optional[float]:
    p0 = _price_on(close, ticker, entry_date)
    p1 = _price_on(close, ticker, exit_date)
    if p0 is None or p1 is None or p0 <= 0:
        return None
    raw = (p1 - p0) / p0
    return raw if direction == "long" else -raw


@dataclass
class PortfolioSimulator:
    initial_capital: float
    hold_trading_days: int
    calendar: List[date]
    close: pd.DataFrame

    def __post_init__(self) -> None:
        self.cash = self.initial_capital
        self.open_lots: List[dict] = []
        self.closed: List[ClosedTrade] = []
        self.equity_history: List[DailySnapshot] = []

    def _mark_equity(self, as_of: date) -> float:
        eq = self.cash
        for lot in self.open_lots:
            ret = trade_return_pct(
                self.close,
                lot["ticker"],
                lot["direction"],
                lot["entry_date"],
                as_of,
            )
            if ret is None:
                continue
            eq += lot["notional"] * (1.0 + ret)
        return eq

    def open_signals(
        self,
        signals: List[TradeSignal],
        signal_date: date,
        *,
        exit_date_override: Optional[date] = None,
    ) -> None:
        if not signals:
            return
        entry_date = next_trading_day(signal_date, self.calendar)
        if entry_date is None:
            return
        if exit_date_override is not None:
            exit_date = exit_date_override
            if exit_date <= entry_date:
                return
        else:
            exit_date = add_trading_days(entry_date, self.hold_trading_days, self.calendar)
            if exit_date is None:
                return
        equity = self._mark_equity(signal_date)
        per_name = equity / len(signals) if equity > 0 else 0.0
        if per_name <= 0:
            return
        for sig in signals:
            self.open_lots.append(
                {
                    "signal_date": signal_date,
                    "entry_date": entry_date,
                    "exit_date": exit_date,
                    "ticker": sig.ticker,
                    "direction": sig.direction,
                    "notional": per_name,
                }
            )
            self.cash -= per_name

    def process_day(self, as_of: date) -> None:
        closed_today = 0
        still_open: List[dict] = []
        for lot in self.open_lots:
            if as_of < lot["exit_date"]:
                still_open.append(lot)
                continue
            ret = trade_return_pct(
                self.close,
                lot["ticker"],
                lot["direction"],
                lot["entry_date"],
                lot["exit_date"],
            )
            if ret is None:
                self.cash += lot["notional"]
                still_open.append({**lot, "exit_date": add_trading_days(as_of, 1, self.calendar) or lot["exit_date"]})
                continue
            pnl = lot["notional"] * ret
            self.cash += lot["notional"] + pnl
            self.closed.append(
                ClosedTrade(
                    signal_date=lot["signal_date"],
                    entry_date=lot["entry_date"],
                    exit_date=lot["exit_date"],
                    ticker=lot["ticker"],
                    direction=lot["direction"],
                    notional_usd=lot["notional"],
                    return_pct=ret,
                    pnl_usd=pnl,
                )
            )
            closed_today += 1
        self.open_lots = still_open
        self.equity_history.append(
            DailySnapshot(
                as_of=as_of,
                equity_usd=self._mark_equity(as_of),
                open_trades=len(self.open_lots),
                closed_trades_today=closed_today,
            )
        )

    def total_return_pct(self) -> float:
        if not self.equity_history:
            return 0.0
        start = self.initial_capital
        end = self.equity_history[-1].equity_usd
        if start <= 0:
            return 0.0
        return (end - start) / start * 100.0


def simulate_signals(
    signals_by_day: Dict[date, List[TradeSignal]],
    *,
    calendar: List[date],
    close: pd.DataFrame,
    initial_capital: float,
    hold_trading_days: int,
    signal_days: Optional[List[date]] = None,
    exit_overrides: Optional[Dict[date, date]] = None,
) -> PortfolioSimulator:
    """Simulate on all days in calendar; open positions only on signal_days."""
    sim = PortfolioSimulator(
        initial_capital=initial_capital,
        hold_trading_days=hold_trading_days,
        calendar=calendar,
        close=close,
    )
    open_on = set(signal_days or list(signals_by_day.keys()))
    overrides = exit_overrides or {}
    for day in calendar:
        if day in open_on:
            sim.open_signals(
                signals_by_day.get(day, []),
                day,
                exit_date_override=overrides.get(day),
            )
        sim.process_day(day)
    return sim


def cohort_return_pct(
    close: pd.DataFrame,
    tickers: List[str],
    entry_date: date,
    exit_date: date,
) -> Optional[float]:
    if not tickers or exit_date <= entry_date:
        return None
    rets = []
    for t in tickers:
        r = trade_return_pct(close, t, "long", entry_date, exit_date)
        if r is not None:
            rets.append(r)
    if not rets:
        return None
    return sum(rets) / len(rets)


def buy_and_hold_return(
    close: pd.DataFrame,
    ticker: str,
    start: date,
    end: date,
    calendar: Optional[List[date]] = None,
) -> Optional[float]:
    cal = calendar or sorted({ts.date() for ts in close.index})
    entry_d = next_trading_day(start - timedelta(days=1), cal)
    if entry_d is None:
        entry_d = cal[0] if cal else start
    exit_d = end
    for d in reversed(cal):
        if d <= end:
            exit_d = d
            break
    ret = trade_return_pct(close, ticker, "long", entry_d, exit_d)
    return ret * 100.0 if ret is not None else None


def equal_weight_day_return(
    close: pd.DataFrame,
    tickers: List[str],
    signal_date: date,
    hold_trading_days: int,
    calendar: List[date],
) -> Optional[float]:
    if not tickers:
        return None
    entry = next_trading_day(signal_date, calendar)
    if entry is None:
        return None
    exit_d = add_trading_days(entry, hold_trading_days, calendar)
    if exit_d is None:
        return None
    rets = []
    for t in tickers:
        r = trade_return_pct(close, t, "long", entry, exit_d)
        if r is not None:
            rets.append(r)
    if not rets:
        return None
    return sum(rets) / len(rets)


def compound_daily_returns(daily_returns: List[float], initial: float = 1000.0) -> float:
    equity = initial
    for r in daily_returns:
        equity *= 1.0 + r
    return equity


def simulate_baseline_from_daily_returns(
    daily_returns: List[Optional[float]],
    initial_capital: float,
) -> float:
    equity = initial_capital
    for r in daily_returns:
        if r is not None:
            equity *= 1.0 + r
    return equity


def build_ticker_universe(signals_by_day: Dict[date, List[TradeSignal]], mentioned_by_day: Dict[date, List[str]]) -> Set[str]:
    universe: Set[str] = set()
    for sigs in signals_by_day.values():
        for s in sigs:
            universe.add(s.ticker)
    for tickers in mentioned_by_day.values():
        universe |= set(tickers)
    universe.add("SPY")
    return universe
