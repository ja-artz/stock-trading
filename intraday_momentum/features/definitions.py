"""Pure point-in-time feature functions."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd


def _bars_as_of(bars: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    if bars.empty:
        return bars
    ts = pd.Timestamp(as_of)
    if bars.index.tz is not None:
        ts = ts.tz_convert(bars.index.tz)
    return bars[bars.index <= ts]


def return_since_open(bars: pd.DataFrame, as_of: datetime) -> float:
    pit = _bars_as_of(bars, as_of)
    if pit.empty:
        return 0.0
    open_px = float(pit["open"].iloc[0])
    last_px = float(pit["close"].iloc[-1])
    if open_px == 0:
        return 0.0
    return (last_px - open_px) / open_px


def return_since_prior_close(
    bars: pd.DataFrame, as_of: datetime, prior_close: Optional[float]
) -> float:
    if prior_close is None or prior_close == 0:
        return 0.0
    pit = _bars_as_of(bars, as_of)
    if pit.empty:
        return 0.0
    last_px = float(pit["close"].iloc[-1])
    return (last_px - prior_close) / prior_close


def gap_pct(bars: pd.DataFrame, prior_close: Optional[float]) -> float:
    if prior_close is None or prior_close == 0 or bars.empty:
        return 0.0
    open_px = float(bars["open"].iloc[0])
    return (open_px - prior_close) / prior_close


def post_open_move_fraction(
    bars: pd.DataFrame, as_of: datetime, prior_close: Optional[float]
) -> float:
    if prior_close is None or prior_close == 0:
        return 1.0
    pit = _bars_as_of(bars, as_of)
    if pit.empty:
        return 0.0
    last_px = float(pit["close"].iloc[-1])
    open_px = float(pit["open"].iloc[0])
    total_move = last_px - prior_close
    if total_move == 0:
        return 1.0
    post_open = last_px - open_px
    return post_open / total_move


def velocity(bars: pd.DataFrame, as_of: datetime, window_min: int) -> float:
    pit = _bars_as_of(bars, as_of)
    if len(pit) < 2:
        return 0.0
    window = pit.tail(max(window_min, 2))
    closes = window["close"].values
    x = np.arange(len(closes))
    if len(x) < 2:
        return 0.0
    slope = np.polyfit(x, closes, 1)[0]
    base = closes[0] if closes[0] != 0 else 1.0
    return float(slope / base)


def acceleration(bars: pd.DataFrame, as_of: datetime, window_min: int) -> float:
    pit = _bars_as_of(bars, as_of)
    if len(pit) < 4:
        return 0.0
    half = max(window_min // 2, 2)
    recent = velocity(pit, as_of, half)
    prior_as_of = pit.index[-min(half + 1, len(pit))]
    prior = velocity(pit, prior_as_of.to_pydatetime(), half)
    return recent - prior


def atr(bars: pd.DataFrame, as_of: datetime, window: int = 14) -> float:
    pit = _bars_as_of(bars, as_of)
    if len(pit) < 2:
        return 0.0
    high = pit["high"]
    low = pit["low"]
    close = pit["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    val = tr.tail(window).mean()
    return float(val) if not np.isnan(val) else 0.0


def extension_atr(bars: pd.DataFrame, as_of: datetime) -> float:
    pit = _bars_as_of(bars, as_of)
    if pit.empty:
        return 0.0
    atr_val = atr(pit, as_of)
    if atr_val == 0:
        return 0.0
    open_px = float(pit["open"].iloc[0])
    last_px = float(pit["close"].iloc[-1])
    return (last_px - open_px) / atr_val


def vwap(bars: pd.DataFrame, as_of: datetime) -> float:
    pit = _bars_as_of(bars, as_of)
    if pit.empty:
        return 0.0
    vol = pit["volume"].sum()
    if vol == 0:
        return float(pit["close"].iloc[-1])
    typical = (pit["high"] + pit["low"] + pit["close"]) / 3.0
    return float((typical * pit["volume"]).sum() / vol)


def extension_vwap_atr(bars: pd.DataFrame, as_of: datetime) -> float:
    pit = _bars_as_of(bars, as_of)
    if pit.empty:
        return 0.0
    atr_val = atr(pit, as_of)
    if atr_val == 0:
        return 0.0
    last_px = float(pit["close"].iloc[-1])
    vwap_px = vwap(pit, as_of)
    return (last_px - vwap_px) / atr_val


def range_position(bars: pd.DataFrame, as_of: datetime) -> float:
    pit = _bars_as_of(bars, as_of)
    if pit.empty:
        return 0.5
    hi = float(pit["high"].max())
    lo = float(pit["low"].min())
    if hi == lo:
        return 0.5
    last_px = float(pit["close"].iloc[-1])
    return (last_px - lo) / (hi - lo)


def realized_vol(bars: pd.DataFrame, as_of: datetime, window: int = 30) -> float:
    pit = _bars_as_of(bars, as_of)
    if len(pit) < 2:
        return 0.0
    rets = pit["close"].pct_change().tail(window).dropna()
    if rets.empty:
        return 0.0
    return float(rets.std())


def time_of_day_fraction(as_of: datetime) -> float:
    ts = pd.Timestamp(as_of).tz_convert("America/New_York")
    minute = (ts.hour * 60 + ts.minute) - (9 * 60 + 30)
    session_minutes = 6.5 * 60
    return max(0.0, min(1.0, minute / session_minutes))


def compute_features(
    bars: pd.DataFrame,
    as_of: datetime,
    prior_close: Optional[float],
) -> Dict[str, float]:
    slope_window = 15
    return {
        "return_since_open": return_since_open(bars, as_of),
        "return_since_prior_close": return_since_prior_close(bars, as_of, prior_close),
        "gap_pct": gap_pct(bars, prior_close),
        "post_open_move_fraction": post_open_move_fraction(bars, as_of, prior_close),
        "velocity_1": velocity(bars, as_of, 1),
        "velocity_5": velocity(bars, as_of, 5),
        "velocity_15": velocity(bars, as_of, slope_window),
        "velocity_30": velocity(bars, as_of, 30),
        "acceleration": acceleration(bars, as_of, slope_window),
        "extension_atr": extension_atr(bars, as_of),
        "extension_vwap_atr": extension_vwap_atr(bars, as_of),
        "range_position": range_position(bars, as_of),
        "realized_vol": realized_vol(bars, as_of),
        "atr": atr(bars, as_of),
        "time_of_day": time_of_day_fraction(as_of),
    }
