#!/usr/bin/env python3
"""
AI Weekly Digest — pipeline orchestrator (decoupled steps).
AI Weekly Digest — 流水线编排器（解耦步骤）。

Orchestrates 5 independent steps, each defined in steps/ as a plain function.
编排5个独立步骤，每个步骤在 steps/ 中定义为普通函数。
Steps communicate through return values / filesystem artifacts.
步骤间通过返回值 / 文件系统产物通信。

5 Steps | 5个步骤:
  0. Load config          | 加载配置          → steps/step0_config.py
  1. Fetch RSS feeds      | 抓取RSS源         → steps/step1_fetch.py
  2. Pre-score & enrich   | 预评分与充实      → steps/step2_enrich.py
  3. Curate with LLM      | LLM筛选           → steps/step3_curate.py
  4. Compose HTML         | 组合HTML           → steps/step4_compose.py
  5. Send email           | 发送邮件           → steps/step5_send.py

Each step can also run standalone:  python -m steps.step1_fetch
每个步骤也可独立运行：python -m steps.step1_fetch

Usage | 用法:
    python run_pipeline.py                  # full pipeline | 完整流水线
    python run_pipeline.py --dry-run        # everything except send | 除发送外的所有步骤
    python run_pipeline.py --fetch-only     # fetch + enrich only | 仅抓取+充实
    python run_pipeline.py --compose-only   # re-compose from latest curated artifact | 从最新产物重新组合
    python run_pipeline.py --to user@example.com   # override recipient | 覆盖收件人
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.utils import (
    log_event,
    tg,
    week_range_label,
)
from core.models import AppConfig
from core.html_composer import HtmlComposer

from steps.step0_config import run as step0_load_config
from steps.step1_fetch import run as step1_fetch
from steps.step2_enrich import run as step2_enrich
from steps.step3_curate import run as step3_curate
from steps.step4_compose import run as step4_compose
from steps.step5_send import run as step5_send


# ── Summary helpers | 摘要辅助函数 ────────────────────────────────────

def success_summary_message(
    article_count: int,
    stories: list[dict[str, Any]],
    send_status: str,
) -> str:
    top_titles = [s.get("title", "") for s in stories[:3]]
    joined = " | ".join(title for title in top_titles if title)
    image_count = sum(1 for s in stories if s.get("image_url"))
    return (
        "✅ AI Weekly Digest v7 ready: %s articles, %s stories, %s images, "
        "top: %s, send: %s"
    ) % (article_count, len(stories), image_count, joined or "n/a", send_status)


def failure_summary_message(message: str) -> str:
    return "❌ AI Weekly Digest failed: %s" % message[:350]


def resolve_recipients(cli_to: Optional[str], config: AppConfig) -> list[str]:
    if cli_to and cli_to.strip():
        return [item.strip() for item in cli_to.split(",") if item.strip()]
    return list(config.recipients)


# ── Full pipeline (calls each step sequentially) | 完整流水线 ────────

def full_pipeline(args: argparse.Namespace) -> int:
    """Execute the 5-step newsletter pipeline: fetch → enrich → curate → compose → send.
    执行5步新闻简报流水线：抓取 → 充实 → 筛选 → 组合 → 发送。
    Returns exit code: 0=success, 1=partial, 2=failure.
    """
    # ── Step 0: Config ───────────────────────────────────────────────────────
    ctx = step0_load_config()
    config = ctx["config"]
    feeds = ctx["feeds"]
    date_label = ctx["date_label"]
    logger = ctx["logger"]

    # ── Step 1: Fetch ────────────────────────────────────────────────────────
    fetch_out = step1_fetch(config, feeds, date_label, logger)

    if fetch_out["abort"]:
        message = fetch_out["abort_message"]
        log_event(logger, logging.ERROR, "fetch_abort", message=message)
        tg(failure_summary_message(message))
        return 2

    articles = fetch_out["articles"]
    failed_feeds = fetch_out["failed_feeds"]

    # ── Step 2: Enrich ───────────────────────────────────────────────────────
    enrich_out = step2_enrich(config, articles, date_label, logger)

    # ── Step 3: Curate ───────────────────────────────────────────────────────
    curate_out = step3_curate(config, enrich_out["articles"], date_label, logger)
    stories = curate_out["stories"]
    llm_failed = curate_out["llm_failed"]

    # ── Step 4: Compose ──────────────────────────────────────────────────────
    compose_out = step4_compose(config, stories, articles, date_label, logger)
    html_body = compose_out["html_body"]

    if args.fetch_only:
        status_code = 1 if failed_feeds else 0
        tg(success_summary_message(len(articles), stories, "fetch-only"))
        print("\n--- Pipeline finished (fetch-only mode) ---")
        return status_code

    if args.dry_run:
        tg(success_summary_message(len(articles), stories, "dry-run"))
        print("\n--- Pipeline finished (dry-run mode, email skipped) ---")
        if llm_failed:
            return 2
        return 1 if failed_feeds else 0

    # ── Step 5: Send ─────────────────────────────────────────────────────────
    recipients = resolve_recipients(args.to, config)
    subject = "🤖 AI Weekly Digest — Week of %s [Issue #%s]" % (
        week_range_label(window_days=config.fetch_window_days),
        config.issue_number,
    )
    send_out = step5_send(config, recipients, subject, html_body, date_label, logger)

    if not send_out["success"]:
        tg(failure_summary_message(send_out["detail"]))
        return 2

    tg(success_summary_message(len(articles), stories, send_out["detail"]))
    print("\n--- Pipeline finished successfully ---")
    if llm_failed:
        return 2
    if failed_feeds:
        return 1
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Weekly Digest — decoupled pipeline orchestrator"
    )
    parser.add_argument(
        "--fetch-only", action="store_true", help="Run fetch + enrich only"
    )
    parser.add_argument(
        "--compose-only",
        action="store_true",
        help="Re-compose HTML from latest curated artifact",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run the full pipeline but skip send"
    )
    parser.add_argument("--to", help="Override recipient email(s), comma-separated")
    return parser.parse_args()


def main() -> int:
    """Main entry point: parse args and run the decoupled pipeline.
    主入口：解析参数并运行解耦的流水线。
    """
    args = parse_args()

    from core.utils import today_label
    print("=" * 60)
    print("  AI Weekly Digest — Pipeline Start")
    print("  Date: %s" % today_label())
    print("=" * 60)
    print()

    try:
        if args.compose_only:
            ctx = step0_load_config()
            composer = HtmlComposer(ctx["config"])
            return composer.compose_only(ctx["logger"])

        return full_pipeline(args)
    except Exception as exc:
        tg(failure_summary_message(str(exc)))
        print("\n!!! FATAL ERROR: %s" % str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
