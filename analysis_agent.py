"""Analysis agent for triage and multi-persona recommendation generation."""

from typing import List, Dict, Any
from anthropic import Anthropic
import json
import config


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

    def _message_create(self, prompt: str, max_tokens: int) -> str:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._extract_response_text(message)

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
- Only US-listed tickers when possible."""

        text = self._message_create(prompt, max_tokens=3000)
        return self._parse_json_object(text)

    def _persona_brief_prompt(self, article: Dict, profile_id: str, shared_context: Dict[str, Any]) -> str:
        persona = PERSONA_INSTRUCTIONS[profile_id]
        sc = json.dumps(shared_context, indent=2)
        return f"""{persona}

Shared factual context (persona-neutral; do not contradict):
{sc}

News story:
{self._article_block(article)}

Provide trading-oriented analysis for US stocks and options aligned with this persona only.
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
- risk_level 1-10; tier 1 quick (weeks), 2 medium, 3 long, 4 speculative."""

    def analyze_story_for_profile(
        self, article: Dict, profile_id: str, shared_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        if profile_id not in PERSONA_INSTRUCTIONS:
            return {"error": f"Unknown profile: {profile_id}", "profile_id": profile_id}
        prompt = self._persona_brief_prompt(article, profile_id, shared_context)
        try:
            text = self._message_create(prompt, max_tokens=8000)
            return self._parse_json_object(text)
        except Exception as e:
            return {"error": str(e), "profile_id": profile_id}

    def analyze_story_multi_profile(self, article: Dict) -> Dict[str, Any]:
        """
        One shared_context call plus one brief per analyst profile.
        Returns envelope: article metadata, shared_context, analyst_profiles.
        """
        title = article.get("title", "")
        envelope: Dict[str, Any] = {
            "article_title": title,
            "article_link": article.get("link", ""),
            "article_published": article.get("published", ""),
            "retrieval_type": article.get("retrieval_type", "unknown"),
            "shared_context": {},
            "analyst_profiles": {},
        }

        try:
            envelope["shared_context"] = self.fetch_shared_context(article)
        except Exception as e:
            print(f"Error fetching shared_context: {e}")
            envelope["shared_context"] = {
                "catalyst_type": "other",
                "timeline": "1-4_weeks",
                "confidence": 1,
                "key_drivers": [],
                "affected_companies": [],
                "error": str(e),
            }

        shared = envelope["shared_context"]

        for pid in config.ANALYST_PROFILES:
            print(f"    Profile: {pid}...")
            envelope["analyst_profiles"][pid] = self.analyze_story_for_profile(article, pid, shared)

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

    def analyze_stories(self, articles: List[Dict]) -> List[Dict]:
        analyses = []
        for i, article in enumerate(articles, 1):
            print(f"\nAnalyzing story {i}/{len(articles)}: {article.get('title', 'Unknown')[:60]}...")
            analyses.append(self.analyze_story_multi_profile(article))
        return analyses


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
    result = agent.analyze_story_multi_profile(test_article)
    print(json.dumps(result, indent=2))
