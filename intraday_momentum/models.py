"""Shared dataclasses for the intraday momentum framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class BarrierOutcome(str, Enum):
    TARGET = "TARGET"
    STOP = "STOP"
    VELOCITY_EXIT = "VELOCITY_EXIT"
    EOD = "EOD"


class DailyVerdict(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    FLAT = "FLAT"
    NO_TRADES = "NO_TRADES"


@dataclass
class Candidate:
    ticker: str
    t0: datetime
    entry_px: float
    features: Dict[str, float] = field(default_factory=dict)
    scan_index: int = 0


@dataclass
class Label:
    outcome: BarrierOutcome
    exit_px: float
    net_return: float
    holding_min: int


@dataclass
class TradeRecord:
    ticker: str
    session_date: date
    t0: datetime
    entry_px: float
    exit_px: float
    outcome: BarrierOutcome
    net_return: float
    holding_min: int
    scan_index: int
    features: Dict[str, float] = field(default_factory=dict)


@dataclass
class DailyResult:
    session_date: date
    verdict: DailyVerdict
    net_pnl_pct: float
    trades: List[TradeRecord] = field(default_factory=list)
    skipped_count: int = 0
    scans_run: List[int] = field(default_factory=list)
    scans_skipped: List[int] = field(default_factory=list)
    notes: str = ""


@dataclass
class IngestSummary:
    mode: str
    sessions_added: int = 0
    sessions_skipped: int = 0
    sessions_failed: int = 0
    sessions_partial: int = 0
    tickers_processed: int = 0
    errors: List[str] = field(default_factory=list)


@dataclass
class CoverageReport:
    ticker_summaries: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class IntradaySnapshot:
    """Point-in-time market snapshot for signal_api."""

    ticker: str
    as_of: datetime
    bars: Any  # DataFrame of minute bars <= as_of
    prior_close: Optional[float] = None
    session_open: Optional[float] = None
