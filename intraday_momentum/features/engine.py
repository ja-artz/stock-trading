"""Feature orchestration at decision time."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from intraday_momentum.features.definitions import compute_features


def compute_all_features(
    bars: pd.DataFrame,
    as_of: datetime,
    prior_close: Optional[float],
    cross_section_returns: Optional[List[float]] = None,
) -> Dict[str, float]:
    features = compute_features(bars, as_of, prior_close)
    if cross_section_returns:
        val = features["return_since_open"]
        rank = sum(1 for r in cross_section_returns if r <= val)
        features["cross_section_rank"] = rank / len(cross_section_returns)
    else:
        features["cross_section_rank"] = 0.5
    return features
