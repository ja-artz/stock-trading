"""Triple-barrier labeling with session-close vertical barrier."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from intraday_momentum.costs.model import CostModel
from intraday_momentum.features.definitions import velocity
from intraday_momentum.models import BarrierOutcome, Label


def label_triple_barrier(
    path: pd.Series,
    entry_px: float,
    target_pct: float,
    stop_pct: float,
    session_close: datetime,
    cost_model: CostModel,
    t0: datetime,
) -> Label:
    target_px = entry_px * (1 + target_pct)
    stop_px = entry_px * (1 - stop_pct)
    t0_ts = pd.Timestamp(t0)
    close_ts = pd.Timestamp(session_close)

    outcome = BarrierOutcome.EOD
    exit_px = float(path.iloc[-1]) if not path.empty else entry_px
    exit_ts = close_ts

    for ts, px in path.items():
        ts = pd.Timestamp(ts)
        if ts <= t0_ts:
            continue
        if ts > close_ts:
            break
        high = float(px) if not hasattr(path, "columns") else float(px)
        bar_high = high
        bar_low = high
        if hasattr(path, "index"):
            # path may be close series; approximate with same px for barrier check
            bar_high = high
            bar_low = high

        eff_target = cost_model.effective_exit_px(target_px)
        eff_stop = cost_model.effective_exit_px(stop_px)

        if bar_high >= target_px:
            outcome = BarrierOutcome.TARGET
            exit_px = target_px
            exit_ts = ts
            break
        if bar_low <= stop_px:
            outcome = BarrierOutcome.STOP
            exit_px = stop_px
            exit_ts = ts
            break
        exit_px = high
        exit_ts = ts

    holding_min = max(0, int((exit_ts - t0_ts).total_seconds() // 60))
    net_return = cost_model.net_return(entry_px, exit_px)
    return Label(outcome=outcome, exit_px=exit_px, net_return=net_return, holding_min=holding_min)


def label_from_session_bars(
    bars: pd.DataFrame,
    t0: datetime,
    entry_px: float,
    target_pct: float,
    stop_pct: float,
    cost_model: CostModel,
    *,
    exit_velocity_threshold: Optional[float] = None,
    slope_window_min: int = 15,
) -> Label:
    session_close = pd.Timestamp(t0).tz_convert("America/New_York").replace(
        hour=16, minute=0, second=0
    )
    forward = bars[bars.index > pd.Timestamp(t0)]
    if forward.empty:
        forward = bars.iloc[-1:]

    target_px = entry_px * (1 + target_pct)
    stop_px = entry_px * (1 - stop_pct)
    outcome = BarrierOutcome.EOD
    exit_px = float(forward["close"].iloc[-1])
    exit_ts = forward.index[-1]

    for ts, row in forward.iterrows():
        if pd.Timestamp(ts) > session_close:
            break
        high = float(row["high"])
        low = float(row["low"])
        if high >= target_px:
            outcome = BarrierOutcome.TARGET
            exit_px = target_px
            exit_ts = ts
            break
        if low <= stop_px:
            outcome = BarrierOutcome.STOP
            exit_px = stop_px
            exit_ts = ts
            break
        if exit_velocity_threshold is not None:
            as_of = pd.Timestamp(ts).to_pydatetime()
            vel = velocity(bars, as_of, slope_window_min)
            if vel < exit_velocity_threshold:
                outcome = BarrierOutcome.VELOCITY_EXIT
                exit_px = float(row["close"])
                exit_ts = ts
                break
        exit_px = float(row["close"])
        exit_ts = ts

    holding_min = max(0, int((pd.Timestamp(exit_ts) - pd.Timestamp(t0)).total_seconds() // 60))
    net_return = cost_model.net_return(entry_px, exit_px)
    return Label(outcome=outcome, exit_px=exit_px, net_return=net_return, holding_min=holding_min)
