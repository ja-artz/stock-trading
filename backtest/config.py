"""Backtest defaults (override via BacktestConfig or CLI)."""

from pathlib import Path

import config as app_config

BACKTEST_CACHE_DIR = Path(app_config.DATA_DIR) / "backtest" / "cache"
NEWS_CACHE_DIR = BACKTEST_CACHE_DIR / "news"
RUNS_CACHE_DIR = BACKTEST_CACHE_DIR / "runs"
PLANS_CACHE_DIR = BACKTEST_CACHE_DIR / "plans"
RESULTS_DIR = Path(app_config.DATA_DIR) / "backtest" / "results"

DEFAULT_DAYS = 90
DEFAULT_WEEKS = 13
DEFAULT_END_DATE = "2026-06-01"  # reference "today" for this project
DEFAULT_HOLD_TRADING_DAYS = 5
DEFAULT_INITIAL_CAPITAL = 1000.0
DEFAULT_PERSONA = "moderate"
# Broad general pool for historical search (date-only after/before returns 0 from Google).
DEFAULT_NEWS_QUERY = "news"
DEFAULT_RANDOM_SEED = 42
