"""Main orchestration script for the trading recommendation system."""

import asyncio
from datetime import datetime

import config
from pipeline.daily_analysis import run_daily_analysis
from pipeline.utils import dedupe_articles, enrich_selected_articles

# Re-export for backward compatibility
__all__ = ["dedupe_articles", "enrich_selected_articles", "format_recommendations", "save_results", "main"]


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
    lines.append(
        f"  Risk: {brief.get('risk_level', 'N/A')}/10 | Tier: {brief.get('recommended_tier', 'N/A')} "
        f"| Return range: {brief.get('expected_return_range', 'N/A')}"
    )
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
            lines.append(
                f"       Tier {rec.get('recommended_tier', 'N/A')}, {rec.get('allocation_percent', 'N/A')}"
            )
            lines.append(f"       {rec.get('rationale', 'N/A')}")
            lines.append(
                f"       Entry: {rec.get('entry_trigger', 'N/A')} | Exit: {rec.get('exit_trigger', 'N/A')}"
            )
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
    """Format analysis results for display."""
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

    return "\n".join(output)


def save_results(analyses: list, filename: str = None):
    """Save analysis results to JSON file."""
    import json
    from pathlib import Path

    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = Path(config.EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        filename = str(export_dir / f"recommendations_{timestamp}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(analyses, f, indent=2)

    print(f"\nResults saved to: {filename}")
    return filename


async def main():
    """Main execution function."""
    from core.store import init_database

    print("=" * 80)
    print("STOCK TRADING RECOMMENDATION SYSTEM")
    print("=" * 80)
    print()

    init_database()

    print("Running daily analysis pipeline...")
    result = await run_daily_analysis(persist=True, export=True, run_type="daily")

    print(f"Collected pool -> {result.article_count} articles, {result.story_count} stories analyzed")
    if result.analysis_run_id:
        print(f"Persisted analysis_run_id={result.analysis_run_id}")

    if not result.analyses:
        print("No analyses produced. Exiting.")
        return

    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(format_recommendations(result.analyses))

    if result.export_path:
        print(f"\nExport: {result.export_path}")

    print("\n" + "=" * 80)
    print("Analysis complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
