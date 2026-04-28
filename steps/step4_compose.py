#!/usr/bin/env python3
"""
Step 4: Compose HTML — 组合HTML

Input:  data/curated-{date}.json (from step3) + data/fetched-{date}.json (from step1)
Output: output/newsletter-{date}.html

将筛选后的故事填充到v7模板，生成最终HTML。
Fills curated stories into v7 template, produces final HTML.

Usage:
    python -m steps.step4_compose
    python -m steps.step4_compose --date 2026-04-24
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
    ensure_directories,
    output_html_path,
    setup_logging,
    today_label,
    week_range_label,
)
from core.html_composer import HtmlComposer


# ── step function | 步骤函数 ─────────────────────────────────────────────────

def run(
    config: AppConfig,
    stories: list[dict[str, Any]],
    scanned_articles: list[Article],
    date_label: str,
    logger: logging.Logger,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compose newsletter HTML and write output files.
    组合新闻简报HTML并写入输出文件。

    Returns dict:
        html_body:    str   — the composed HTML string
        output_path:  str   — path to output HTML file
    """
    print()
    print("=" * 60)
    print("  STEP 4 / 5 : COMPOSE NEWSLETTER HTML")
    print("=" * 60)

    composer = HtmlComposer(config)
    html_body = composer.compose(
        stories,
        scanned_articles,
        week_range_label(window_days=config.fetch_window_days),
        meta=meta or {},
    )
    composer.write_outputs(date_label, html_body, logger)

    return {
        "html_body": html_body,
        "output_path": str(output_html_path(date_label)),
    }


# ── standalone entry | 独立入口 ──────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Step 4: Compose newsletter HTML")
    parser.add_argument("--date", help="Date label (default: today)")
    args = parser.parse_args()

    from steps.step0_config import run as load_config
    from steps.step1_fetch import run as fetch
    from steps.step2_enrich import run as enrich
    from steps.step3_curate import run as curate

    ctx = load_config(date_label=args.date)
    fetch_result = fetch(ctx["config"], ctx["feeds"], ctx["date_label"], ctx["logger"])
    if fetch_result["abort"]:
        print("\n❌ Cannot compose: %s" % fetch_result["abort_message"])
        return 2

    enrich_result = enrich(ctx["config"], fetch_result["articles"], ctx["date_label"], ctx["logger"])
    curate_result = curate(ctx["config"], enrich_result["articles"], ctx["date_label"], ctx["logger"])
    result = run(
        ctx["config"], curate_result["stories"], fetch_result["articles"],
        ctx["date_label"], ctx["logger"], meta=curate_result.get("meta"),
    )
    print("\n✅ HTML composed: %s" % result["output_path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
