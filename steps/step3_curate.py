#!/usr/bin/env python3
"""
Step 3: Curate with LLM — LLM筛选

Input:  data/enriched-{date}.json (from step2)
Output: data/curated-{date}.json

使用LLM筛选最佳故事，失败时降级为启发式排名。
Curates best stories using LLM, falls back to heuristic ranking on failure.

Usage:
    python -m steps.step3_curate
    python -m steps.step3_curate --date 2026-04-24
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
    curated_path,
    ensure_directories,
    setup_logging,
    today_label,
)
from core.content_curator import ContentCurator


# ── step function | 步骤函数 ─────────────────────────────────────────────────

def run(
    config: AppConfig,
    articles: list[Article],
    date_label: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    """
    Curate articles with LLM, save curated-{date}.json.
    使用LLM筛选文章，保存 curated-{date}.json。

    Returns dict:
        stories:          list[dict]  — curated story dicts
        llm_failed:       bool        — True if LLM curation failed and fallback was used
        output_path:      str         — path to curated JSON
    """
    print()
    print("=" * 60)
    print("  STEP 3 / 5 : CURATE WITH LLM")
    print("=" * 60)

    curator = ContentCurator(config, logger)
    curated, llm_failed = curator.curate(articles, date_label)

    return {
        "stories": curated,
        "llm_failed": llm_failed,
        "output_path": str(curated_path(date_label)),
    }


# ── standalone entry | 独立入口 ──────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Step 3: Curate with LLM")
    parser.add_argument("--date", help="Date label (default: today)")
    args = parser.parse_args()

    from steps.step0_config import run as load_config
    from steps.step1_fetch import run as fetch
    from steps.step2_enrich import run as enrich

    ctx = load_config(date_label=args.date)
    fetch_result = fetch(ctx["config"], ctx["feeds"], ctx["date_label"], ctx["logger"])
    if fetch_result["abort"]:
        print("\n❌ Cannot curate: %s" % fetch_result["abort_message"])
        return 2

    enrich_result = enrich(ctx["config"], fetch_result["articles"], ctx["date_label"], ctx["logger"])
    result = run(ctx["config"], enrich_result["articles"], ctx["date_label"], ctx["logger"])
    print("\n✅ Curated %d stories (llm_failed=%s)" % (len(result["stories"]), result["llm_failed"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
