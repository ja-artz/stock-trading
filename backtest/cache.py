"""JSON cache for historical news and daily pipeline outputs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, List, Optional

from backtest.config import NEWS_CACHE_DIR, PLANS_CACHE_DIR, RUNS_CACHE_DIR


def _day_key(d: date) -> str:
    return d.isoformat()


def news_cache_path(day: date) -> Path:
    return NEWS_CACHE_DIR / f"{_day_key(day)}.json"


def runs_cache_path(day: date) -> Path:
    return RUNS_CACHE_DIR / f"{_day_key(day)}.json"


def load_json(path: Path) -> Optional[Any]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_cached_news(day: date) -> Optional[List[dict]]:
    return load_json(news_cache_path(day))


def save_cached_news(day: date, articles: List[dict]) -> None:
    save_json(news_cache_path(day), articles)


def load_cached_run(day: date) -> Optional[dict]:
    return load_json(runs_cache_path(day))


def save_cached_run(day: date, payload: dict) -> None:
    save_json(runs_cache_path(day), payload)


def plans_cache_path(day: date) -> Path:
    return PLANS_CACHE_DIR / f"{_day_key(day)}.json"


def load_cached_plan(day: date) -> Optional[dict]:
    return load_json(plans_cache_path(day))


def save_cached_plan(day: date, payload: dict) -> None:
    save_json(plans_cache_path(day), payload)
