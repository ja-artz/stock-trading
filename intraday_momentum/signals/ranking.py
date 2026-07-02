"""Candidate scoring and ranking when oversubscribed."""

from __future__ import annotations

from typing import List

from intraday_momentum.models import Candidate


def score_candidate(candidate: Candidate) -> float:
    f = candidate.features
    return (
        f.get("return_since_open", 0.0) * 2.0
        + f.get("velocity_15", 0.0) * 100.0
        + f.get("rvol", 0.0) * 0.5
        + f.get("post_open_move_fraction", 0.0) * 1.0
        - f.get("extension_atr", 0.0) * 0.25
    )


def rank_candidates(candidates: List[Candidate]) -> List[Candidate]:
    return sorted(candidates, key=score_candidate, reverse=True)


def select_candidates(
    candidates: List[Candidate],
    max_take: int,
) -> tuple[List[Candidate], List[Candidate]]:
    ranked = rank_candidates(candidates)
    taken = ranked[:max_take]
    skipped = ranked[max_take:]
    return taken, skipped
