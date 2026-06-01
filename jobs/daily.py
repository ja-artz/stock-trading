"""Run daily analysis job."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.store import init_database
from pipeline.daily_analysis import run_daily_analysis
from main import format_recommendations, save_results


async def main():
    init_database()
    print("Running daily analysis...")
    result = await run_daily_analysis(persist=True, export=True, run_type="daily")
    print(f"Articles: {result.article_count}, Stories analyzed: {result.story_count}")
    if result.analysis_run_id:
        print(f"Saved analysis_run_id={result.analysis_run_id}")
    if result.export_path:
        print(f"Export: {result.export_path}")
    if result.analyses:
        print(format_recommendations(result.analyses))
    else:
        print("No analyses produced.")


if __name__ == "__main__":
    asyncio.run(main())
