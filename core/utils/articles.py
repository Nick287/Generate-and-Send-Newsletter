"""
Article operations: deduplication, persistence (save/load JSON).
文章操作：去重、持久化（JSON保存/加载）。
"""

from __future__ import annotations

import json
import re
import string
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from core.models import Article
from core.utils.dates import article_datetime, article_sort_key


# ── Title dedup helpers | 标题去重工具 ────────────────────────────────────────

def normalize_title(title: str) -> str:
    lowered = (title or "").lower()
    translator = str.maketrans("", "", string.punctuation)
    normalized = lowered.translate(translator)
    return re.sub(r"\s+", " ", normalized).strip()


def title_tokens(title: str) -> set[str]:
    normalized = normalize_title(title)
    return {token for token in normalized.split(" ") if token}


def title_similarity(a: str, b: str) -> float:
    a_tokens = title_tokens(a)
    b_tokens = title_tokens(b)
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    denominator = max(len(a_tokens), len(b_tokens))
    if denominator == 0:
        return 0.0
    return overlap / float(denominator)


def better_article(candidate: Article, current: Article) -> Article:
    """Choose the better article between two duplicates."""
    candidate_summary_len = len(candidate.raw_summary or "")
    current_summary_len = len(current.raw_summary or "")
    if candidate_summary_len > current_summary_len:
        return candidate
    if candidate_summary_len < current_summary_len:
        return current
    candidate_has_date = article_datetime(candidate) is not None
    current_has_date = article_datetime(current) is not None
    if candidate_has_date and not current_has_date:
        return candidate
    if current_has_date and not candidate_has_date:
        return current
    return (
        candidate
        if article_sort_key(candidate) < article_sort_key(current)
        else current
    )


def deduplicate_articles(articles: list[Article]) -> list[Article]:
    """Deduplicate by exact link match, then by title similarity (>0.6)."""
    by_link: dict[str, Article] = {}
    for article in articles:
        existing = by_link.get(article.link)
        if existing is None:
            by_link[article.link] = article
        else:
            by_link[article.link] = better_article(article, existing)

    deduped: list[Article] = []
    for article in sorted(by_link.values(), key=article_sort_key):
        matched_index: Optional[int] = None
        for index, kept in enumerate(deduped):
            if title_similarity(article.title, kept.title) > 0.6:
                matched_index = index
                break
        if matched_index is None:
            deduped.append(article)
            continue
        deduped[matched_index] = better_article(article, deduped[matched_index])

    return sorted(deduped, key=article_sort_key)


# ── Persistence | 持久化 ────────────────────────────────────────────────────

def save_articles(path: Path, articles: list[Article]) -> None:
    payload = [asdict(article) for article in articles]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_articles(path: Path) -> list[Article]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Expected %s to contain a JSON array" % path)
    articles: list[Article] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        articles.append(
            Article(
                title=str(item.get("title", "")).strip(),
                link=str(item.get("link", "")).strip(),
                source_name=str(item.get("source_name", "")).strip(),
                category=str(item.get("category", "")).strip(),
                published_date=item.get("published_date"),
                raw_summary=str(item.get("raw_summary", "")).strip(),
                full_text_excerpt=str(item.get("full_text_excerpt", "")).strip(),
                og_image=item.get("og_image"),
                image_url=item.get("image_url"),
                pre_score=(
                    float(item["pre_score"])
                    if item.get("pre_score") is not None
                    else None
                ),
            )
        )
    return articles
