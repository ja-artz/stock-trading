"""Candidate detection at scan times."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import pandas as pd

from intraday_momentum.data.store import BarStore
from intraday_momentum.features.engine import compute_all_features
from intraday_momentum.models import Candidate
from intraday_momentum.settings import StrategyConfig


def evaluate_trigger(
    ticker: str,
    bars: pd.DataFrame,
    as_of: datetime,
    strategy: StrategyConfig,
    store: BarStore,
    session_date,
    cross_section_returns: Optional[List[float]] = None,
) -> Optional[Candidate]:
    if bars.empty:
        return None

    trigger = strategy.trigger
    prior_close = store.prior_session_close(ticker, session_date)
    features = compute_all_features(bars, as_of, prior_close, cross_section_returns)

    move_ref = trigger.get("move_reference", "open")
    move_threshold = float(trigger.get("move_threshold", 0.05))
    if move_ref == "prior_close":
        move = features["return_since_prior_close"]
    else:
        move = features["return_since_open"]
    if move < move_threshold:
        return None

    slope_window = int(trigger.get("slope_window_min", 15))
    velocity = features.get(f"velocity_{slope_window}", features["velocity_15"])
    velocity_threshold = trigger.get("velocity_threshold")
    if velocity_threshold is not None and velocity < float(velocity_threshold):
        return None

    rvol_threshold = float(trigger.get("rvol_threshold", 3.0))
    baseline = store.rvol_baseline_volume(ticker, session_date, as_of)
    pit = bars[bars.index <= pd.Timestamp(as_of).tz_convert(bars.index.tz)]
    cum_vol = float(pit["volume"].sum()) if not pit.empty else 0.0
    rvol = (cum_vol / baseline) if baseline and baseline > 0 else 0.0
    features["rvol"] = rvol
    if rvol < rvol_threshold:
        return None

    min_post_open = float(trigger.get("min_post_open_fraction", 0.5))
    if features["post_open_move_fraction"] < min_post_open:
        return None

    entry_px = float(pit["close"].iloc[-1])
    return Candidate(ticker=ticker, t0=as_of, entry_px=entry_px, features=features)
