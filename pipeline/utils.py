"""Shared pipeline helpers."""

import re


def normalize_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip().lower())
    return re.sub(r"[^a-z0-9 ]", "", cleaned)


def dedupe_articles(articles: list) -> list:
    seen_links = set()
    seen_titles = set()
    deduped = []
    for article in articles:
        link_key = (article.get("link") or "").strip().lower()
        title_key = normalize_text(article.get("title", ""))
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
    original_by_title = {normalize_text(a.get("title", "")): a for a in all_articles}
    enriched = []
    for article in selected_articles:
        original = original_by_title.get(normalize_text(article.get("title", "")))
        if original:
            enriched.append({
                "title": article.get("title", original.get("title", "")),
                "source": article.get("source", original.get("source", "Unknown")),
                "summary": article.get("summary", original.get("summary", "")),
                "published": original.get("published", "Unknown"),
                "link": original.get("link", ""),
                "retrieval_type": article.get("retrieval_type", "unknown"),
            })
        else:
            enriched.append({
                "title": article.get("title", ""),
                "source": article.get("source", "Unknown"),
                "summary": article.get("summary", ""),
                "published": article.get("published", "Unknown"),
                "link": article.get("link", ""),
                "retrieval_type": article.get("retrieval_type", "unknown"),
            })
    return enriched
