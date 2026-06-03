"""Carry forward multi-persona consensus for open / watch recommendations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

PERSONA_KEYS = ("aggressive", "moderate", "minimal_risk")


def normalize_persona_consensus(raw: Any) -> Optional[Dict[str, bool]]:
    if not raw or not isinstance(raw, dict):
        return None
    out: Dict[str, bool] = {}
    for key in PERSONA_KEYS:
        if key in raw:
            out[key] = bool(raw[key])
    return out or None


def consensus_agree_count(consensus: Optional[dict]) -> int:
    c = normalize_persona_consensus(consensus)
    if not c:
        return 0
    return sum(1 for v in c.values() if v)


def has_meaningful_consensus(consensus: Optional[dict]) -> bool:
    return consensus_agree_count(consensus) > 0


def item_qualifies_for_consensus_carry_forward(item: dict) -> bool:
    action = (item.get("action") or "").strip().lower()
    status = (item.get("status") or "pending").strip().lower()
    rationale = (item.get("rationale") or "").lower()
    if action in ("watch", "hold"):
        return True
    if status in ("pending", "deferred"):
        return True
    if "carry forward" in rationale or "carried forward" in rationale:
        return True
    return False


def _ticker_key(item: dict) -> Optional[str]:
    t = (item.get("ticker") or "").strip().upper()
    return t or None


def index_prior_consensus_by_ticker(prior_items: List[dict]) -> Dict[str, Dict[str, bool]]:
    """Newest-first prior items → latest meaningful consensus per ticker."""
    index: Dict[str, Dict[str, bool]] = {}
    for item in prior_items:
        sym = _ticker_key(item)
        if not sym or sym in index:
            continue
        c = normalize_persona_consensus(item.get("persona_consensus"))
        if has_meaningful_consensus(c):
            index[sym] = c  # type: ignore[assignment]
    return index


def apply_carry_forward_persona_consensus(
    items: List[dict],
    prior_items: List[dict],
) -> List[dict]:
    """Fill missing / all-false persona_consensus from prior plan line items (same ticker)."""
    prior_by_ticker = index_prior_consensus_by_ticker(prior_items)
    if not prior_by_ticker:
        return items

    out: List[dict] = []
    for raw in items:
        item = dict(raw)
        if not item_qualifies_for_consensus_carry_forward(item):
            out.append(item)
            continue
        if has_meaningful_consensus(item.get("persona_consensus")):
            out.append(item)
            continue
        sym = _ticker_key(item)
        prior = prior_by_ticker.get(sym) if sym else None
        if prior:
            item["persona_consensus"] = dict(prior)
            item["persona_consensus_carried_forward"] = True
        out.append(item)
    return out


def enrich_plan_items_persona_consensus(
    items: List[dict],
    prior_items: List[dict],
) -> List[dict]:
    """In-place enrichment for hydrated API rows (does not persist)."""
    enriched = apply_carry_forward_persona_consensus(items, prior_items)
    return enriched
