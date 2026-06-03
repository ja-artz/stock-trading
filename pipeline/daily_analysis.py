"""Daily news collection and multi-persona analysis pipeline."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import config
from analysis_agent import AnalysisAgent
from news_collector import NewsCollector
from retrieval_agent import RetrievalAgent
from pipeline.progress import ProgressCallback, emit_progress
from pipeline.utils import dedupe_articles, enrich_selected_articles


@dataclass
class DailyAnalysisResult:
    analyses: List[dict]
    analysis_run_id: Optional[int]
    export_path: Optional[str]
    article_count: int
    story_count: int


async def run_daily_analysis(
    *,
    persist: bool = True,
    export: bool = True,
    run_type: str = "daily",
    household_id: int = 1,
    on_progress: Optional[ProgressCallback] = None,
    articles: Optional[List[dict]] = None,
) -> DailyAnalysisResult:
    emit_progress(
        on_progress,
        "start",
        "Starting daily analysis pipeline",
        set_stage=True,
    )

    if articles is None:
        collector = NewsCollector(
            rss_url=config.GOOGLE_NEWS_RSS_URL,
            max_age_hours=config.MAX_NEWS_AGE_HOURS,
        )
        emit_progress(
            on_progress,
            "fetch_news",
            f"Fetching RSS news (pool up to {config.NEWS_FETCH_POOL_SIZE} articles, max age {config.MAX_NEWS_AGE_HOURS}h)…",
        )
        articles = await asyncio.to_thread(
            collector.get_general_news, num_results=config.NEWS_FETCH_POOL_SIZE
        )
        emit_progress(
            on_progress,
            "fetch_news",
            f"Fetched {len(articles)} articles from feed",
            set_stage=False,
        )
    else:
        emit_progress(
            on_progress,
            "fetch_news",
            f"Using {len(articles)} pre-fetched articles",
            set_stage=False,
        )
    if not articles:
        emit_progress(on_progress, "done", "No articles found in feed — nothing to analyze", set_stage=True)
        return DailyAnalysisResult([], None, None, 0, 0)

    retrieval_agent = RetrievalAgent()
    emit_progress(
        on_progress,
        "retrieval",
        (
            f"Running headline + upside retrieval agents in parallel "
            f"({config.RETRIEVAL_MIN_STORIES_PER_AGENT}–{config.RETRIEVAL_MAX_STORIES_PER_AGENT} stories each)…"
        ),
    )
    headline_result, upside_result = await asyncio.gather(
        retrieval_agent.select_top_stories(
            mode="headline",
            news_articles=articles,
            min_stories=config.RETRIEVAL_MIN_STORIES_PER_AGENT,
            max_stories=config.RETRIEVAL_MAX_STORIES_PER_AGENT,
        ),
        retrieval_agent.select_top_stories(
            mode="upside",
            news_articles=articles,
            min_stories=config.RETRIEVAL_MIN_STORIES_PER_AGENT,
            max_stories=config.RETRIEVAL_MAX_STORIES_PER_AGENT,
        ),
    )

    headline_articles = [{**a, "retrieval_type": "headline"} for a in headline_result.get("articles", [])]
    upside_articles = [{**a, "retrieval_type": "upside"} for a in upside_result.get("articles", [])]
    emit_progress(
        on_progress,
        "retrieval",
        f"Retrieval done — headline: {len(headline_articles)}, upside: {len(upside_articles)}",
        set_stage=False,
    )

    emit_progress(on_progress, "merge", "Merging and deduplicating story candidates…")
    merged = dedupe_articles(headline_articles + upside_articles)
    emit_progress(
        on_progress,
        "merge",
        f"{len(merged)} unique candidates after merge",
        set_stage=False,
    )
    if not merged:
        emit_progress(on_progress, "done", "No stories after merge — stopping", set_stage=True)
        return DailyAnalysisResult([], None, None, len(articles), 0)

    analysis_agent = AnalysisAgent()
    emit_progress(
        on_progress,
        "triage",
        f"Triage: selecting up to {config.ACTIONABLE_STORIES_TO_ANALYZE} actionable stories (LLM)…",
    )
    triage = await asyncio.to_thread(
        analysis_agent.select_actionable_stories,
        merged,
        config.ACTIONABLE_STORIES_TO_ANALYZE,
    )
    selected = triage.get("articles", [])
    reasoning = (triage.get("reasoning") or "").strip()
    if reasoning:
        emit_progress(on_progress, "triage", f"Triage: {reasoning[:240]}", set_stage=False)
    emit_progress(
        on_progress,
        "triage",
        f"{len(selected)} stories selected for full analysis",
        set_stage=False,
    )
    if not selected:
        emit_progress(on_progress, "done", "Triage selected no stories — stopping", set_stage=True)
        return DailyAnalysisResult([], None, None, len(articles), 0)

    formatted = enrich_selected_articles(selected, articles)
    emit_progress(
        on_progress,
        "analyze",
        f"Analyzing {len(formatted)} stories (shared context + {len(config.ANALYST_PROFILES)} personas each)…",
    )
    analyses = await analysis_agent.analyze_stories_async(formatted, on_progress=on_progress)

    emit_progress(on_progress, "validate", "Validating tickers and refining invalid symbols…")
    analyses = await analysis_agent.validate_and_refine_envelopes_async(
        formatted, analyses, on_progress=on_progress
    )

    export_path = None
    if export:
        emit_progress(on_progress, "export", "Writing JSON export…")
        export_dir = Path(config.EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = str(export_dir / f"recommendations_{ts}.json")
        await asyncio.to_thread(
            lambda: Path(export_path).write_text(
                json.dumps(analyses, indent=2), encoding="utf-8"
            )
        )
        emit_progress(on_progress, "export", f"Export saved: {export_path}", set_stage=False)

    run_id = None
    if persist:
        emit_progress(on_progress, "persist", "Saving analysis run to database…")

        def _persist() -> int:
            from core.store import create_analysis_run, init_database

            init_database()
            return create_analysis_run(
                household_id, analyses, run_type=run_type, export_path=export_path
            )

        run_id = await asyncio.to_thread(_persist)
        emit_progress(
            on_progress,
            "persist",
            f"Saved analysis_run_id={run_id}",
            set_stage=False,
        )

    if persist:
        try:
            from core.tier_discipline import run_daily_discipline

            await asyncio.to_thread(run_daily_discipline, 1)
        except Exception:
            pass

    emit_progress(
        on_progress,
        "done",
        f"Complete — {len(analyses)} stories analyzed from {len(articles)} articles",
        set_stage=True,
    )
    return DailyAnalysisResult(
        analyses=analyses,
        analysis_run_id=run_id,
        export_path=export_path,
        article_count=len(articles),
        story_count=len(analyses),
    )
