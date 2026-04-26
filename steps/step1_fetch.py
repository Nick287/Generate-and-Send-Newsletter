#!/usr/bin/env python3
"""
Step 1: Fetch RSS Feeds — 抓取RSS源

Input:  config + feeds (from step0) or config.yaml/feeds.yaml on disk
Output: data/fetched-{date}.json

从RSS源并行抓取文章，按日期过滤、去重，保存为JSON产物。
Fetches articles from RSS feeds in parallel, filters by date, deduplicates, saves as JSON artifact.

Usage:
    python -m steps.step1_fetch
    python -m steps.step1_fetch --date 2026-04-24
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

from core.models import AppConfig, FeedSource
from core.utils import (
    ensure_directories,
    fetched_path,
    log_event,
    setup_logging,
    tg,
    today_label,
)
from core.feed_fetcher import FeedFetcher


# ── step function | 步骤函数 ─────────────────────────────────────────────────

def run(
    config: AppConfig,
    feeds: list[FeedSource],
    date_label: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    """
    Fetch RSS feeds and save fetched-{date}.json.
    抓取RSS源并保存 fetched-{date}.json。

    Returns dict:
        articles:       list[Article]   — deduplicated articles
        failed_feeds:   list[str]       — names of feeds that failed
        total_feeds:    int
        reused:         bool            — True if loaded from cache
        output_path:    str             — path to fetched JSON
    """
    print("=" * 60)
    print("  STEP 1 / 5 : FETCH RSS FEEDS")
    print("=" * 60)

    fetcher = FeedFetcher(config, logger)
    result = fetcher.fetch_all(feeds, date_label)

    # Check failure threshold
    failure_ratio = 0.0
    if result.total_feeds:
        failure_ratio = len(result.failed_feeds) / float(result.total_feeds)

    output = {
        "articles": result.articles,
        "failed_feeds": result.failed_feeds,
        "total_feeds": result.total_feeds,
        "reused": result.reused,
        "failure_ratio": failure_ratio,
        "output_path": str(fetched_path(date_label)),
    }

    if failure_ratio > config.fetch_fail_threshold:
        output["abort"] = True
        output["abort_message"] = "Fetch aborted: %s/%s feeds failed" % (
            len(result.failed_feeds), result.total_feeds,
        )
    elif not result.articles:
        output["abort"] = True
        output["abort_message"] = "No articles fetched"
    else:
        output["abort"] = False

    return output


# ── standalone entry | 独立入口 ──────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Step 1: Fetch RSS feeds")
    parser.add_argument("--date", help="Date label (default: today)")
    args = parser.parse_args()

    from steps.step0_config import run as load_config
    ctx = load_config(date_label=args.date)

    result = run(ctx["config"], ctx["feeds"], ctx["date_label"], ctx["logger"])
    if result["abort"]:
        print("\n❌ %s" % result["abort_message"])
        return 2
    print("\n✅ Fetched %d articles" % len(result["articles"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
