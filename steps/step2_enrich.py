#!/usr/bin/env python3
"""
Step 2: Pre-score & Enrich — 预评分与充实

Input:  data/fetched-{date}.json (from step1)
Output: data/enriched-{date}.json

对文章进行LLM预评分，提取高分候选的全文和OG图片。
LLM pre-scores articles, fetches full text and OG images for top candidates.

Usage:
    python -m steps.step2_enrich
    python -m steps.step2_enrich --date 2026-04-24
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.models import AppConfig, Article
from core.utils import (
    enriched_path,
    ensure_directories,
    setup_logging,
    today_label,
)
from core.article_enricher import ArticleEnricher


# ── step function | 步骤函数 ─────────────────────────────────────────────────

def run(
    config: AppConfig,
    articles: list[Article],
    date_label: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    """
    Pre-score and enrich articles, save enriched-{date}.json.
    预评分并充实文章，保存 enriched-{date}.json。

    Returns dict:
        articles:     list[Article]   — enriched articles (top candidates)
        output_path:  str             — path to enriched JSON
    """
    print()
    print("=" * 60)
    print("  STEP 2 / 5 : PRE-SCORE & ENRICH ARTICLES")
    print("=" * 60)

    enricher = ArticleEnricher(config, logger)
    enriched = enricher.enrich(articles, date_label)

    return {
        "articles": enriched,
        "output_path": str(enriched_path(date_label)),
    }


# ── standalone entry | 独立入口 ──────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Step 2: Pre-score & enrich articles")
    parser.add_argument("--date", help="Date label (default: today)")
    args = parser.parse_args()

    from steps.step0_config import run as load_config
    from steps.step1_fetch import run as fetch

    ctx = load_config(date_label=args.date)
    fetch_result = fetch(ctx["config"], ctx["feeds"], ctx["date_label"], ctx["logger"])
    if fetch_result["abort"]:
        print("\n❌ Cannot enrich: %s" % fetch_result["abort_message"])
        return 2

    result = run(ctx["config"], fetch_result["articles"], ctx["date_label"], ctx["logger"])
    print("\n✅ Enriched %d articles" % len(result["articles"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
