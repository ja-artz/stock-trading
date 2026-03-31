"""Main orchestration script for the trading recommendation system."""

import json
import asyncio
from datetime import datetime
import re
from news_collector import NewsCollector
from retrieval_agent import RetrievalAgent
from analysis_agent import AnalysisAgent
import config


def _format_shared_context_block(sc: dict) -> list:
    lines = []
    if not sc:
        return ["  (no shared context)"]
    lines.append(f"  Catalyst: {sc.get('catalyst_type', 'N/A')}")
    lines.append(f"  Timeline: {sc.get('timeline', 'N/A')}")
    lines.append(f"  Confidence: {sc.get('confidence', 'N/A')}/10")
    if sc.get("error"):
        lines.append(f"  Note: {sc.get('error')}")
    drivers = sc.get("key_drivers") or []
    if drivers:
        lines.append("  Key drivers:")
        for d in drivers:
            lines.append(f"    - {d}")
    affected = sc.get("affected_companies") or []
    if affected:
        lines.append("  Affected companies:")
        for company in affected:
            lines.append(
                f"    - {company.get('ticker', 'N/A')} ({company.get('company_name', 'N/A')}) "
                f"impact={company.get('impact_type', 'N/A')} dir={company.get('expected_direction', 'N/A')}"
            )
    return lines


def _format_profile_brief(profile_id: str, brief: dict) -> list:
    lines = []
    lines.append(f"  --- {profile_id.upper().replace('_', ' ')} ---")
    if brief.get("error"):
        lines.append(f"  Error: {brief.get('error')}")
        return lines
    lines.append(f"  Thesis: {brief.get('thesis', 'N/A')}")
    lines.append(f"  Risk: {brief.get('risk_level', 'N/A')}/10 | Tier: {brief.get('recommended_tier', 'N/A')} | Return range: {brief.get('expected_return_range', 'N/A')}")
    milestones = brief.get("key_milestones") or []
    if milestones:
        lines.append("  Milestones:")
        for m in milestones:
            lines.append(f"    - {m}")
    recs = brief.get("recommendations") or []
    if recs:
        lines.append("  Recommendations:")
        for j, rec in enumerate(recs, 1):
            lines.append(f"    {j}. {rec.get('ticker', 'N/A')} {rec.get('instrument_type', 'N/A')}")
            lines.append(f"       Tier {rec.get('recommended_tier', 'N/A')}, {rec.get('allocation_percent', 'N/A')}")
            lines.append(f"       {rec.get('rationale', 'N/A')}")
            lines.append(f"       Entry: {rec.get('entry_trigger', 'N/A')} | Exit: {rec.get('exit_trigger', 'N/A')}")
            if rec.get("stop_loss"):
                lines.append(f"       Stop: {rec.get('stop_loss')}")
    else:
        lines.append("  Recommendations: (none)")
    actions = brief.get("portfolio_actions") or []
    if actions:
        lines.append("  Portfolio actions:")
        for pa in actions:
            lines.append(
                f"    - {pa.get('action', 'N/A')} {pa.get('instrument', 'N/A')} "
                f"({pa.get('sizing_hint', 'N/A')}): {pa.get('rationale', 'N/A')}"
            )
    risks = brief.get("risks") or []
    if risks:
        lines.append("  Risks:")
        for risk in risks:
            lines.append(f"    - {risk}")
    alts = brief.get("alternative_plays") or []
    if alts:
        lines.append("  Alternatives:")
        for alt in alts:
            lines.append(f"    - {alt}")
    return lines


def format_recommendations(analyses: list) -> str:
    """Format analysis results for display (multi-persona envelope or legacy flat dict)."""
    output = []
    output.append("=" * 80)
    output.append("TRADING RECOMMENDATIONS")
    output.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append("=" * 80)

    for i, analysis in enumerate(analyses, 1):
        if "error" in analysis and "analyst_profiles" not in analysis:
            output.append(f"\n[ERROR] Story {i}: {analysis.get('article_title', 'Unknown')}")
            output.append(f"Error: {analysis.get('error', 'Unknown error')}")
            continue

        output.append(f"\n{'='*80}")
        title = analysis.get("article_title", "Unknown")
        output.append(f"STORY {i}: {title}")
        output.append(f"{'='*80}")
        output.append(f"Retrieval: {analysis.get('retrieval_type', 'N/A')}")
        if analysis.get("article_link"):
            output.append(f"Link: {analysis.get('article_link')}")

        if "analyst_profiles" in analysis:
            output.append("\nShared context (factual):")
            output.extend(_format_shared_context_block(analysis.get("shared_context") or {}))
            profiles = analysis.get("analyst_profiles") or {}
            for pid in config.ANALYST_PROFILES:
                brief = profiles.get(pid, {})
                output.append("")
                output.extend(_format_profile_brief(pid, brief))
            continue

        # Legacy single-profile shape
        output.append(f"Catalyst Type: {analysis.get('catalyst_type', 'N/A')}")
        output.append(f"Timeline: {analysis.get('timeline', 'N/A')}")
        output.append(f"Risk Level: {analysis.get('risk_level', 'N/A')}/10")
        output.append(f"Recommended Tier: {analysis.get('recommended_tier', 'N/A')}")
        output.append(f"Expected Return: {analysis.get('expected_return_range', 'N/A')}")
        output.append(f"\nThesis:")
        output.append(f"  {analysis.get('thesis', 'N/A')}")
        affected = analysis.get("affected_companies", [])
        if affected:
            output.append(f"\nAffected Companies:")
            for company in affected:
                output.append(f"  - {company.get('ticker', 'N/A')} ({company.get('company_name', 'N/A')})")
                output.append(f"    Impact: {company.get('impact_type', 'N/A')}, Direction: {company.get('expected_direction', 'N/A')}")
        recommendations = analysis.get("recommendations", [])
        if recommendations:
            output.append(f"\nTrading Recommendations:")
            for j, rec in enumerate(recommendations, 1):
                output.append(f"\n  {j}. {rec.get('ticker', 'N/A')} - {rec.get('instrument_type', 'N/A')}")
                output.append(f"     Tier: {rec.get('recommended_tier', 'N/A')}, Allocation: {rec.get('allocation_percent', 'N/A')}")
                output.append(f"     Rationale: {rec.get('rationale', 'N/A')}")
                output.append(f"     Entry: {rec.get('entry_trigger', 'N/A')}")
                output.append(f"     Exit: {rec.get('exit_trigger', 'N/A')}")
                if rec.get("stop_loss"):
                    output.append(f"     Stop Loss: {rec.get('stop_loss')}")
        else:
            output.append(f"\nNo specific recommendations generated for this story.")
        risks = analysis.get("risks", [])
        if risks:
            output.append(f"\nRisks:")
            for risk in risks:
                output.append(f"  - {risk}")
        milestones = analysis.get("key_milestones", [])
        if milestones:
            output.append(f"\nKey Milestones to Watch:")
            for milestone in milestones:
                output.append(f"  - {milestone}")

    return "\n".join(output)


def save_results(analyses: list, filename: str = None):
    """Save analysis results to JSON file."""
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recommendations_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(analyses, f, indent=2)
    
    print(f"\nResults saved to: {filename}")


def _normalize_text(value: str) -> str:
    """Normalize text for fuzzy dedupe checks."""
    cleaned = re.sub(r"\s+", " ", (value or "").strip().lower())
    return re.sub(r"[^a-z0-9 ]", "", cleaned)


def dedupe_articles(articles: list) -> list:
    """Deduplicate stories by link first, then normalized title."""
    seen_links = set()
    seen_titles = set()
    deduped = []
    for article in articles:
        link_key = (article.get("link") or "").strip().lower()
        title_key = _normalize_text(article.get("title", ""))
        if link_key and link_key in seen_links:
            continue
        if title_key and title_key in seen_titles:
            continue
        if link_key:
            seen_links.add(link_key)
        if title_key:
            seen_titles.add(title_key)
        deduped.append(article)
    return deduped


def enrich_selected_articles(selected_articles: list, all_articles: list) -> list:
    """Rehydrate selected stories with original link/published fields when possible."""
    original_by_title = {_normalize_text(a.get("title", "")): a for a in all_articles}
    enriched = []
    for article in selected_articles:
        original = original_by_title.get(_normalize_text(article.get("title", "")))
        if original:
            enriched.append({
                "title": article.get("title", original.get("title", "")),
                "source": article.get("source", original.get("source", "Unknown")),
                "summary": article.get("summary", original.get("summary", "")),
                "published": original.get("published", "Unknown"),
                "link": original.get("link", ""),
                "retrieval_type": article.get("retrieval_type", "unknown")
            })
        else:
            enriched.append({
                "title": article.get("title", ""),
                "source": article.get("source", "Unknown"),
                "summary": article.get("summary", ""),
                "published": article.get("published", "Unknown"),
                "link": article.get("link", ""),
                "retrieval_type": article.get("retrieval_type", "unknown")
            })
    return enriched


async def main():
    """Main execution function."""
    print("=" * 80)
    print("STOCK TRADING RECOMMENDATION SYSTEM - MVP")
    print("=" * 80)
    print()
    
    # Step 1: Collect news (optional - can also let retrieval agent fetch directly)
    print("Step 1: Collecting news...")
    collector = NewsCollector(
        rss_url=config.GOOGLE_NEWS_RSS_URL,
        max_age_hours=config.MAX_NEWS_AGE_HOURS
    )
    
    articles = collector.get_general_news(num_results=config.NEWS_FETCH_POOL_SIZE)
    print(f"Collected {len(articles)} news articles (target: {config.NEWS_FETCH_POOL_SIZE})")
    
    if not articles:
        print("No articles found. Exiting.")
        return
    
    # Step 2: Select candidate stories using dual retrieval agents
    print("\nStep 2: Running dual retrieval agents...")
    retrieval_agent = RetrievalAgent()

    headline_result = await retrieval_agent.select_top_stories(
        mode="headline",
        news_articles=articles,
        min_stories=config.RETRIEVAL_MIN_STORIES_PER_AGENT,
        max_stories=config.RETRIEVAL_MAX_STORIES_PER_AGENT
    )

    upside_result = await retrieval_agent.select_top_stories(
        mode="upside",
        news_articles=articles,
        min_stories=config.RETRIEVAL_MIN_STORIES_PER_AGENT,
        max_stories=config.RETRIEVAL_MAX_STORIES_PER_AGENT
    )

    headline_articles = [
        {**article, "retrieval_type": "headline"}
        for article in headline_result.get("articles", [])
    ]
    upside_articles = [
        {**article, "retrieval_type": "upside"}
        for article in upside_result.get("articles", [])
    ]
    merged_candidates = dedupe_articles(headline_articles + upside_articles)

    if headline_result.get("reasoning"):
        print(f"\nHeadline Retrieval Reasoning: {headline_result['reasoning']}")
    if upside_result.get("reasoning"):
        print(f"\nUpside Retrieval Reasoning: {upside_result['reasoning']}")

    print(
        f"Headline candidates: {len(headline_articles)}, "
        f"Upside candidates: {len(upside_articles)}, "
        f"Merged unique candidates: {len(merged_candidates)}"
    )

    if not merged_candidates:
        print("No candidate articles selected. Exiting.")
        return

    # Step 3: Triage and analyze selected stories
    analysis_agent = AnalysisAgent()
    triage = analysis_agent.select_actionable_stories(
        merged_candidates,
        max_stories=config.ACTIONABLE_STORIES_TO_ANALYZE
    )
    selected_actionable = triage.get("articles", [])
    print(f"\nTriage Reasoning: {triage.get('reasoning', '')}")
    print(f"Selected {len(selected_actionable)} actionable stories for full analysis")

    if not selected_actionable:
        print("No actionable stories selected. Exiting.")
        return

    formatted_articles = enrich_selected_articles(selected_actionable, articles)
    print(f"\nStep 3: Analyzing {len(formatted_articles)} selected stories...")
    analyses = analysis_agent.analyze_stories(formatted_articles)
    
    # Step 4: Display results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    formatted_output = format_recommendations(analyses)
    print(formatted_output)
    
    # Step 5: Save results
    save_results(analyses)
    
    print("\n" + "=" * 80)
    print("Analysis complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
