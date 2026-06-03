"""Analysis agent for triage and multi-persona recommendation generation."""

import asyncio
import random
import time
from typing import List, Dict, Any, Optional
from anthropic import Anthropic
from anthropic import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
import json
import config
from core.indirect_effects import (
    empty_indirect_effects,
    map_indirect_effects,
    normalize_shared_context,
    should_run_indirect_analysis,
)


PERSONA_INSTRUCTIONS = {
    "aggressive": """You are an aggressive event-driven trader. Prioritize asymmetric payoff and speed of execution.
Prefer higher-conviction directional views, shorter horizons when justified, and use of options (calls/puts) when they improve payoff/risk.
Accept wider drawdowns for meaningful upside; size recommendations accordingly in language (not dollar amounts unless relative).""",
    "moderate": """You are a balanced sell-side style analyst. Prioritize sensible risk/reward and diversified expression of the thesis.
Mix stocks and options conservatively; emphasize clear triggers and risk controls. Default to mainstream instruments and liquid names.""",
    "minimal_risk": """You are a capital-preservation focused analyst. Minimize tail risk and avoid speculative structures unless essential.
Prefer hedges, smaller notionals, wider stops or defined-risk options, and explicit 'no trade' when catalyst is too uncertain.""",
}


class AnalysisAgent:
    """LLM agent: shared factual context plus three analyst personas per story."""

    def __init__(self):
        self.client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL

    def _extract_response_text(self, message) -> str:
        text_blocks = []
        for block in message.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                text_blocks.append(text)
        return "\n".join(text_blocks).strip()

    def _parse_json_object(self, response_text: str) -> Dict[str, Any]:
        if "```json" in response_text:
            response_text = response_text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```", 1)[1].split("```", 1)[0].strip()
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            first_brace = response_text.find("{")
            last_brace = response_text.rfind("}")
            while first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                candidate = response_text[first_brace : last_brace + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    last_brace = response_text.rfind("}", 0, last_brace)
            raise

    def _is_retryable_anthropic(self, exc: BaseException) -> bool:
        if isinstance(exc, (APIConnectionError, APITimeoutError)):
            return True
        if isinstance(exc, RateLimitError):
            return True
        if isinstance(exc, APIStatusError):
            return exc.status_code in (429, 500, 502, 503, 529)
        return False

    def _message_create(self, prompt: str, max_tokens: int) -> str:
        """Call Anthropic with retries for transient overload / rate limits / server errors."""
        max_attempts = getattr(config, "ANTHROPIC_MAX_RETRIES", 6)
        base_delay = getattr(config, "ANTHROPIC_RETRY_BASE_DELAY_SEC", 2.0)
        last_exc: Optional[BaseException] = None
        for attempt in range(max_attempts):
            try:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return self._extract_response_text(message)
            except Exception as e:
                last_exc = e
                if not self._is_retryable_anthropic(e) or attempt == max_attempts - 1:
                    raise
                delay = base_delay * (2**attempt) + random.uniform(0, 1.5)
                code = getattr(e, "status_code", None)
                if isinstance(e, APIStatusError):
                    code = e.status_code
                print(
                    f"Anthropic transient error (attempt {attempt + 1}/{max_attempts}, "
                    f"code={code}): {e!s}. Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc

    def _article_block(self, article: Dict) -> str:
        return f"""Title: {article.get('title', 'N/A')}
Source: {article.get('source', 'Unknown')}
Published: {article.get('published', 'Unknown')}
Summary: {article.get('summary', 'No summary available')}
Link: {article.get('link', '')}"""

    def fetch_shared_context(self, article: Dict) -> Dict[str, Any]:
        """Persona-neutral factual catalyst context (single LLM call)."""
        prompt = f"""You extract factual catalyst context from a news story for US-listed equities. Do not give portfolio advice, sizing, or trade ideas.

News story:
{self._article_block(article)}

Return valid JSON only, no markdown, with exactly this structure:
{{
  "story_domain": "market_direct|macro_geopolitical|public_health|disaster_climate|policy_fiscal|other",
  "run_indirect_analysis": false,
  "catalyst_type": "M&A|regulatory|geopolitical|earnings|product_launch|management_change|other",
  "timeline": "1-4_weeks|1-6_months|6-12_months|12+_months",
  "confidence": 1,
  "key_drivers": ["driver1", "driver2"],
  "affected_companies": [
    {{
      "ticker": "SYMBOL",
      "company_name": "Full Company Name",
      "impact_type": "primary|secondary|tertiary",
      "expected_direction": "bullish|bearish|neutral",
      "confidence": 1
    }}
  ]
}}

Rules:
- confidence fields are integers 1-10.
- key_drivers: at most 5 short, factual statements tied to the article.
- affected_companies may be empty if mapping is unreliable.
- Only US-listed tickers when possible.
- story_domain:
  * market_direct: earnings, M&A, single-company product/management news, corporate actions.
  * macro_geopolitical: wars, elections, sanctions, international conflict, diplomacy.
  * public_health: pandemics, outbreaks, FDA/public health policy with broad economic impact.
  * disaster_climate: natural disasters, climate events with regional/global supply impact.
  * policy_fiscal: central bank, rates, fiscal stimulus, broad regulation affecting many sectors.
  * other: use when none fit cleanly.
- run_indirect_analysis: true when the story is NOT primarily about one listed company's corporate action;
  set false for market_direct / earnings / M&A / product_launch / management_change focused stories."""

        text = self._message_create(prompt, max_tokens=3000)
        return normalize_shared_context(self._parse_json_object(text))

    def fetch_indirect_effects(
        self, article: Dict, shared_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Map 2nd/3rd-order hypotheses for macro-style stories (single LLM call)."""
        if not should_run_indirect_analysis(shared_context):
            return empty_indirect_effects(enabled=False, reason="not_applicable")
        try:
            return map_indirect_effects(
                self._article_block(article),
                shared_context,
                self._message_create,
                self._parse_json_object,
            )
        except Exception as e:
            print(f"Error mapping indirect effects: {e}")
            return empty_indirect_effects(enabled=False, reason=str(e))

    def _persona_brief_prompt(
        self,
        article: Dict,
        profile_id: str,
        shared_context: Dict[str, Any],
        indirect_effects: Optional[Dict[str, Any]] = None,
    ) -> str:
        persona = PERSONA_INSTRUCTIONS[profile_id]
        sc = json.dumps(shared_context, indent=2)
        indirect_block = ""
        ie = indirect_effects or {}
        if ie.get("enabled"):
            indirect_block = f"""
Indirect effects (hypotheses only — do NOT duplicate as full recommendations):
{json.dumps(ie, indent=2)}
"""
        persona_indirect_rules = ""
        if profile_id == "aggressive" and ie.get("enabled"):
            persona_indirect_rules = """
- You may cite at most ONE indirect ticker in alternative_plays (one string), from the top causal chain.
- Do NOT add indirect tickers to recommendations[] — those stay first-order / liquid expressions of the headline.
"""
        elif profile_id in ("moderate", "minimal_risk") and ie.get("enabled"):
            persona_indirect_rules = """
- Do NOT add indirect / 2nd-order tickers to recommendations[].
- You may mention indirect risks in risks[] only; leave alternative_plays empty of indirect trades.
"""
        return f"""{persona}

Shared factual context (persona-neutral; do not contradict):
{sc}
{indirect_block}
News story:
{self._article_block(article)}

Provide trading-oriented analysis for US stocks and options aligned with this persona only.
Focus recommendations on first-order, liquid expressions of the headline catalyst.
{persona_indirect_rules}
Keep thesis under 200 words; limit lists to at most 5 items each.

Return valid JSON only, no markdown, with exactly this structure:
{{
  "profile_id": "{profile_id}",
  "thesis": "Why this matters for trading under this risk stance",
  "risk_level": 1,
  "recommended_tier": 1,
  "expected_return_range": "X% to Y%",
  "key_milestones": ["..."],
  "recommendations": [
    {{
      "ticker": "SYMBOL",
      "instrument_type": "stock|call_option|put_option",
      "recommended_tier": 1,
      "conviction_grade": "A_plus|A|B_plus|B",
      "allocation_percent": "wording only, relative to tier or risk budget",
      "rationale": "...",
      "entry_trigger": "...",
      "exit_trigger": "...",
      "stop_loss": "or null"
    }}
  ],
  "portfolio_actions": [
    {{
      "action": "trim|add|hedge|hold|watch",
      "instrument": "ticker or index/ETF or option structure",
      "rationale": "how this relates to an existing book",
      "sizing_hint": "small|medium|large"
    }}
  ],
  "risks": ["..."],
  "alternative_plays": ["..."]
}}

Guidelines:
- US-listed only; correct tickers (e.g. AAPL not APPL).
- If no clear trade, use empty recommendations and explain in thesis.
- risk_level 1-10; recommended_tier 1 quick (1-4 weeks), 2 medium (3-6 months), 3 long (6-12 months). Do not use tier 4 for trades (portfolio dry powder is separate)."""

    def analyze_story_for_profile(
        self,
        article: Dict,
        profile_id: str,
        shared_context: Dict[str, Any],
        indirect_effects: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if profile_id not in PERSONA_INSTRUCTIONS:
            return {"error": f"Unknown profile: {profile_id}", "profile_id": profile_id}
        prompt = self._persona_brief_prompt(
            article, profile_id, shared_context, indirect_effects
        )
        try:
            text = self._message_create(prompt, max_tokens=8000)
            return self._parse_json_object(text)
        except Exception as e:
            return {"error": str(e), "profile_id": profile_id}

    async def analyze_story_multi_profile_async(self, article: Dict) -> Dict[str, Any]:
        """
        One shared_context call, then three persona briefs in parallel (async gather).
        Returns envelope: article metadata, shared_context, analyst_profiles.
        """
        title = article.get("title", "")
        envelope: Dict[str, Any] = {
            "article_title": title,
            "article_link": article.get("link", ""),
            "article_published": article.get("published", ""),
            "retrieval_type": article.get("retrieval_type", "unknown"),
            "shared_context": {},
            "indirect_effects": empty_indirect_effects(enabled=False),
            "analyst_profiles": {},
        }

        try:
            envelope["shared_context"] = await asyncio.to_thread(
                self.fetch_shared_context, article
            )
        except Exception as e:
            print(f"Error fetching shared_context: {e}")
            envelope["shared_context"] = normalize_shared_context(
                {
                    "story_domain": "other",
                    "run_indirect_analysis": False,
                    "catalyst_type": "other",
                    "timeline": "1-4_weeks",
                    "confidence": 1,
                    "key_drivers": [],
                    "affected_companies": [],
                    "error": str(e),
                }
            )

        shared = envelope["shared_context"]

        if should_run_indirect_analysis(shared):
            print("    Indirect effects mapper…")
            envelope["indirect_effects"] = await asyncio.to_thread(
                self.fetch_indirect_effects, article, shared
            )
        else:
            envelope["indirect_effects"] = empty_indirect_effects(
                enabled=False, reason="market_direct_or_disabled"
            )

        indirect = envelope["indirect_effects"]

        tasks = [
            asyncio.to_thread(
                self.analyze_story_for_profile, article, pid, shared, indirect
            )
            for pid in config.ANALYST_PROFILES
        ]
        print(f"    Personas (parallel): {', '.join(config.ANALYST_PROFILES)}")
        briefs = await asyncio.gather(*tasks)
        for pid, brief in zip(config.ANALYST_PROFILES, briefs):
            envelope["analyst_profiles"][pid] = brief

        return envelope

    def select_actionable_stories(self, articles: List[Dict], max_stories: int) -> Dict:
        if not articles:
            return {"articles": [], "reasoning": "No candidate stories provided"}

        bounded_max = max(1, min(max_stories, len(articles)))
        formatted_candidates = []
        for i, article in enumerate(articles):
            formatted_candidates.append(
                f"[{i}] {article.get('title', '')}\n"
                f"    Source: {article.get('source', 'Unknown')}\n"
                f"    Published: {article.get('published', 'Unknown')}\n"
                f"    Summary: {article.get('summary', '')[:400]}\n"
                f"    RetrievalType: {article.get('retrieval_type', 'unknown')}\n"
            )
        prompt = f"""You are triaging candidate financial news stories for actionability.

Select the top {bounded_max} stories that are most likely to produce actionable trading opportunities.
Do not produce trading recommendations yet. Only choose which stories should move to full analysis.

Candidates:
{chr(10).join(formatted_candidates)}

Return valid JSON only in this exact structure:
{{
  "selected_indices": [0, 3, 5],
  "reasoning": "Short explanation"
}}
"""
        try:
            response_text = self._message_create(prompt, max_tokens=2000)
            parsed = self._parse_json_object(response_text)
            indices = parsed.get("selected_indices", [])
            reasoning = parsed.get("reasoning", "")
            selected = []
            for idx in indices:
                if isinstance(idx, int) and 0 <= idx < len(articles):
                    selected.append(articles[idx])

            if not selected:
                selected = articles[:bounded_max]
                reasoning = "Fallback selection used due to empty/invalid triage output."

            return {"articles": selected[:bounded_max], "reasoning": reasoning}
        except Exception as e:
            print(f"Error selecting actionable stories: {e}")
            return {
                "articles": articles[:bounded_max],
                "reasoning": f"Fallback selection used due to triage error: {e}",
            }

    async def analyze_stories_async(
        self, articles: List[Dict], on_progress=None
    ) -> List[Dict]:
        analyses = []
        personas = ", ".join(config.ANALYST_PROFILES)
        for i, article in enumerate(articles, 1):
            title = (article.get("title") or "Unknown")[:72]
            msg = f"Story {i}/{len(articles)}: {title} — shared context + personas ({personas})"
            print(f"\nAnalyzing story {i}/{len(articles)}: {article.get('title', 'Unknown')[:60]}...")
            if on_progress:
                from pipeline.progress import emit_progress

                emit_progress(on_progress, "analyze", msg, set_stage=i == 1)
            analyses.append(await self.analyze_story_multi_profile_async(article))
            if on_progress:
                from pipeline.progress import emit_progress

                emit_progress(
                    on_progress,
                    "analyze",
                    f"Finished story {i}/{len(articles)}: {title}",
                    set_stage=False,
                )
        return analyses

    def refine_envelope_for_invalid_tickers(
        self,
        article: Dict[str, Any],
        envelope: Dict[str, Any],
        invalid_tickers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Second pass: rewrite the full analysis envelope so tickers align with real US listings.
        Called when validation finds symbols that do not resolve via yfinance.
        """
        envelope_clean = {k: v for k, v in envelope.items() if k != "validation"}
        inv = json.dumps(invalid_tickers, indent=2)
        payload = json.dumps(envelope_clean, indent=2)
        prompt = f"""You previously produced this multi-persona analysis JSON for a news story.

Automated ticker validation reported these symbols as invalid or unresolvable (wrong, delisted, or hallucinated):
{inv}

News story (for context):
{self._article_block(article)}

Your task: return the COMPLETE analysis envelope again as valid JSON only (no markdown).
Fix all issues:
- Replace wrong tickers with correct US-listed symbols where the story clearly implies a company, or remove the row.
- Update company_name in shared_context.affected_companies to match the corrected ticker.
- Fix analyst_profiles.*.recommendations[].ticker and portfolio_actions[].instrument when the first token is a ticker.
- Keep the same structure: article_title, article_link, article_published, retrieval_type, shared_context, indirect_effects, analyst_profiles with keys {list(config.ANALYST_PROFILES)}.
- Fix indirect_effects.causal_chains[].tickers[].ticker if invalid; remove bad rows.
- If a persona had an error object, you may leave it or replace with a valid brief.
- Do not add a "validation" key.

Original envelope:
{payload}"""

        try:
            text = self._message_create(prompt, max_tokens=16000)
            parsed = self._parse_json_object(text)
            for key in (
                "article_title",
                "article_link",
                "article_published",
                "retrieval_type",
                "indirect_effects",
            ):
                if key in envelope_clean and key not in parsed:
                    parsed[key] = envelope_clean[key]
            return parsed
        except Exception as e:
            print(f"Ticker refinement parse failed: {e}")
            envelope_clean["refinement_error"] = str(e)
            return envelope_clean

    async def validate_and_refine_envelopes_async(
        self, articles: List[Dict], analyses: List[Dict], on_progress=None
    ) -> List[Dict]:
        """Attach validation; optionally one LLM refinement pass when tickers fail checks."""
        from validation import validate_envelope

        out: List[Dict[str, Any]] = []
        for i, (article, env) in enumerate(zip(articles, analyses), 1):
            if "analyst_profiles" not in env:
                out.append(env)
                continue

            title = (env.get("article_title") or "")[:60]
            if on_progress:
                from pipeline.progress import emit_progress

                emit_progress(
                    on_progress,
                    "validate",
                    f"Validating {i}/{len(analyses)}: {title}",
                    set_stage=i == 1,
                )

            report = await asyncio.to_thread(validate_envelope, article, env)
            meta: Dict[str, Any] = {"initial": report, "refinement_applied": False}

            if report.get("invalid_tickers") and config.ENABLE_TICKER_REFINEMENT_LOOP:
                print(f"  Ticker refinement: {env.get('article_title', '')[:55]}...")
                if on_progress:
                    from pipeline.progress import emit_progress

                    emit_progress(
                        on_progress,
                        "validate",
                        f"Refining invalid tickers for: {title}",
                        set_stage=False,
                    )
                refined = await asyncio.to_thread(
                    self.refine_envelope_for_invalid_tickers,
                    article,
                    env,
                    report["invalid_tickers"],
                )
                meta["refinement_applied"] = True
                refined["validation"] = meta
                refined["validation"]["after_refinement"] = await asyncio.to_thread(
                    validate_envelope, article, refined
                )
                out.append(refined)
            else:
                env["validation"] = meta
                out.append(env)
        return out


if __name__ == "__main__":
    test_article = {
        "title": "Example: Major Tech Company Announces Merger",
        "summary": "A major technology company announced plans to merge with a competitor.",
        "source": "Financial Times",
        "published": "2025-01-15T10:00:00",
        "link": "https://example.com/news",
        "retrieval_type": "headline",
    }

    agent = AnalysisAgent()
    result = asyncio.run(agent.analyze_story_multi_profile_async(test_article))
    print(json.dumps(result, indent=2))
