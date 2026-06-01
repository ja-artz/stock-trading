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
) -> DailyAnalysisResult:
    collector = NewsCollector(
        rss_url=config.GOOGLE_NEWS_RSS_URL,
        max_age_hours=config.MAX_NEWS_AGE_HOURS,
    )
    articles = collector.get_general_news(num_results=config.NEWS_FETCH_POOL_SIZE)
    if not articles:
        return DailyAnalysisResult([], None, None, 0, 0)

    retrieval_agent = RetrievalAgent()
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
    merged = dedupe_articles(headline_articles + upside_articles)
    if not merged:
        return DailyAnalysisResult([], None, None, len(articles), 0)

    analysis_agent = AnalysisAgent()
    triage = analysis_agent.select_actionable_stories(
        merged, max_stories=config.ACTIONABLE_STORIES_TO_ANALYZE
    )
    selected = triage.get("articles", [])
    if not selected:
        return DailyAnalysisResult([], None, None, len(articles), 0)

    formatted = enrich_selected_articles(selected, articles)
    analyses = await analysis_agent.analyze_stories_async(formatted)
    analyses = await analysis_agent.validate_and_refine_envelopes_async(formatted, analyses)

    export_path = None
    if export:
        export_dir = Path(config.EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = str(export_dir / f"recommendations_{ts}.json")
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(analyses, f, indent=2)

    run_id = None
    if persist:
        from core.store import create_analysis_run, init_database

        init_database()
        run_id = create_analysis_run(
            household_id, analyses, run_type=run_type, export_path=export_path
        )

    return DailyAnalysisResult(
        analyses=analyses,
        analysis_run_id=run_id,
        export_path=export_path,
        article_count=len(articles),
        story_count=len(analyses),
    )
