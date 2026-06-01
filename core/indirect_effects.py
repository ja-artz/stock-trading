"""Second/third-order (indirect) market effects mapping for macro-style news stories."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

import config

STORY_DOMAINS = (
    "market_direct",
    "macro_geopolitical",
    "public_health",
    "disaster_climate",
    "policy_fiscal",
    "other",
)

MARKET_DIRECT_CATALYSTS = frozenset(
    {"earnings", "m&a", "ma", "product_launch", "management_change"}
)

INDIRECT_STORY_DOMAINS = frozenset(
    {"macro_geopolitical", "public_health", "disaster_climate", "policy_fiscal"}
)


def _norm_catalyst(catalyst_type: Optional[str]) -> str:
    if not catalyst_type:
        return ""
    return str(catalyst_type).strip().lower().replace(" ", "_")


def should_run_indirect_analysis(shared_context: Dict[str, Any]) -> bool:
    """Whether to invoke the indirect-effects mapper for this story."""
    if not getattr(config, "ENABLE_INDIRECT_EFFECTS_ANALYSIS", True):
        return False
    if shared_context.get("run_indirect_analysis") is False:
        return False
    if shared_context.get("run_indirect_analysis") is True:
        return True
    domain = (shared_context.get("story_domain") or "").strip().lower()
    if domain == "market_direct":
        return False
    if domain in INDIRECT_STORY_DOMAINS:
        return True
    catalyst = _norm_catalyst(shared_context.get("catalyst_type"))
    if catalyst in MARKET_DIRECT_CATALYSTS:
        return False
    if catalyst in ("geopolitical", "regulatory", "other"):
        return domain != "market_direct"
    return False


def normalize_shared_context(shared_context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure story_domain / run_indirect_analysis are consistent after LLM output."""
    sc = dict(shared_context or {})
    domain = (sc.get("story_domain") or "other").strip().lower()
    if domain not in STORY_DOMAINS:
        domain = "other"
    sc["story_domain"] = domain

    catalyst = _norm_catalyst(sc.get("catalyst_type"))
    if catalyst in MARKET_DIRECT_CATALYSTS and domain not in INDIRECT_STORY_DOMAINS:
        domain = "market_direct"
        sc["story_domain"] = domain

    if "run_indirect_analysis" not in sc or sc.get("run_indirect_analysis") is None:
        sc["run_indirect_analysis"] = should_run_indirect_analysis(sc)
    else:
        sc["run_indirect_analysis"] = bool(sc["run_indirect_analysis"])

    return sc


def empty_indirect_effects(*, enabled: bool = False, reason: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "enabled": enabled,
        "causal_chains": [],
        "discarded_obvious": [],
    }
    if reason:
        out["skip_reason"] = reason
    return out


def build_indirect_effects_prompt(article_block: str, shared_context: Dict[str, Any]) -> str:
    max_chains = getattr(config, "INDIRECT_MAX_CHAINS", 3)
    sc_json = json.dumps(shared_context, indent=2)
    return f"""You map second- and third-order (indirect) US equity effects from a news story.
Do NOT give portfolio sizing or trade instructions. Hypothesis generation only.

News story:
{article_block}

Shared factual context (do not contradict):
{sc_json}

Return valid JSON only, no markdown, with exactly this structure:
{{
  "enabled": true,
  "causal_chains": [
    {{
      "order": 2,
      "steps": ["headline event", "intermediate mechanism", "market consequence"],
      "sectors": ["short_sector_label"],
      "tickers": [
        {{"ticker": "SYMBOL", "role": "beneficiary|headwind|hedge", "confidence": 1}}
      ],
      "thesis_one_liner": "one sentence",
      "time_horizon": "1-4_weeks|1-6_months|6-12_months|12+_months",
      "already_priced_risk": "high|medium|low",
      "falsifiers": ["what would invalidate this chain"],
      "liquidity_ok": true
    }}
  ],
  "discarded_obvious": ["crowded first-order trade the market will chase — brief reason"]
}}

Rules:
- Provide at most {max_chains} causal_chains, ranked by strongest thesis first.
- Include at least one chain with order 3 (event → intermediate step → distant listed beneficiary).
- steps: 3–5 short strings per chain showing the causal logic.
- tickers: US-listed, liquid symbols only; confidence integers 1–10 per ticker row.
- discarded_obvious: list obvious headline trades (e.g. vaccine names on a pandemic story) you are NOT elevating.
- already_priced_risk: honest assessment if the chain is likely crowded in price.
- liquidity_ok: false if beneficiaries are illiquid micro-caps.
- No markdown."""


def normalize_indirect_effects(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Clamp and normalize mapper output."""
    max_chains = getattr(config, "INDIRECT_MAX_CHAINS", 3)
    enabled = bool(raw.get("enabled", True))
    chains_in = raw.get("causal_chains") or []
    chains: List[Dict[str, Any]] = []
    if isinstance(chains_in, list):
        for ch in chains_in[:max_chains]:
            if not isinstance(ch, dict):
                continue
            tickers_in = ch.get("tickers") or []
            tickers: List[Dict[str, Any]] = []
            if isinstance(tickers_in, list):
                for t in tickers_in:
                    if not isinstance(t, dict):
                        continue
                    sym = (t.get("ticker") or "").strip().upper()
                    if not sym:
                        continue
                    conf = t.get("confidence", 1)
                    try:
                        conf = max(1, min(10, int(conf)))
                    except (TypeError, ValueError):
                        conf = 1
                    tickers.append(
                        {
                            "ticker": sym,
                            "role": (t.get("role") or "beneficiary").strip().lower(),
                            "confidence": conf,
                        }
                    )
            order = ch.get("order", 2)
            try:
                order = int(order)
            except (TypeError, ValueError):
                order = 2
            apr = (ch.get("already_priced_risk") or "medium").strip().lower()
            if apr not in ("high", "medium", "low"):
                apr = "medium"
            chains.append(
                {
                    "order": order,
                    "steps": [str(s) for s in (ch.get("steps") or [])[:5]],
                    "sectors": [str(s) for s in (ch.get("sectors") or [])[:5]],
                    "tickers": tickers,
                    "thesis_one_liner": str(ch.get("thesis_one_liner") or "")[:500],
                    "time_horizon": ch.get("time_horizon") or "1-6_months",
                    "already_priced_risk": apr,
                    "falsifiers": [str(f) for f in (ch.get("falsifiers") or [])[:5]],
                    "liquidity_ok": bool(ch.get("liquidity_ok", True)),
                }
            )
    discarded = raw.get("discarded_obvious") or []
    if not isinstance(discarded, list):
        discarded = []
    return {
        "enabled": enabled and len(chains) > 0,
        "causal_chains": chains,
        "discarded_obvious": [str(x) for x in discarded[:8]],
    }


def map_indirect_effects(
    article_block: str,
    shared_context: Dict[str, Any],
    message_create: Callable[[str, int], str],
    parse_json: Callable[[str], Dict[str, Any]],
) -> Dict[str, Any]:
    """Run the indirect-effects LLM mapper."""
    if not should_run_indirect_analysis(shared_context):
        return empty_indirect_effects(
            enabled=False,
            reason="market_direct_or_disabled",
        )
    prompt = build_indirect_effects_prompt(article_block, shared_context)
    text = message_create(prompt, 4000)
    parsed = parse_json(text)
    return normalize_indirect_effects(parsed)
