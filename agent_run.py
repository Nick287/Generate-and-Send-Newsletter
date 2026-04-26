#!/usr/bin/env python3
"""
AI Weekly Digest — Agent Framework workflow entry point.
AI 周刊摘要 — Agent Framework 工作流入口。

Uses Microsoft Agent Framework's functional workflow API (@workflow + @step)
to orchestrate the same 5-step newsletter pipeline with:
使用 Microsoft Agent Framework 的函数式工作流 API 编排相同的5步流水线，提供：

  - Per-step checkpointing (skip expensive re-execution on resume)
    每步检查点（恢复时跳过已完成的昂贵步骤）
  - Built-in observability (executor_invoked / executor_completed events)
    内置可观测性（executor_invoked / executor_completed 事件）
  - Streaming support (watch progress in real time)
    流式支持（实时查看进度）

Usage | 用法:
    python agent_run.py                         # full pipeline | 完整流水线
    python agent_run.py --dry-run               # skip send | 跳过发送
    python agent_run.py --to user@example.com   # override recipient | 覆盖收件人
    python agent_run.py --stream                # stream events | 流式输出事件
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from agent_framework import step, workflow, InMemoryCheckpointStorage

from core.utils import (
    log_event,
    tg,
    week_range_label,
)
from core.models import AppConfig

# Import the existing step functions (sync) — we wrap them in async @step
# 导入现有的同步步骤函数 — 用 async @step 包装
from steps.step0_config import run as _step0_config
from steps.step1_fetch import run as _step1_fetch
from steps.step2_enrich import run as _step2_enrich
from steps.step3_curate import run as _step3_curate
from steps.step4_compose import run as _step4_compose
from steps.step5_send import run as _step5_send


# ── Checkpoint storage | 检查点存储 ──────────────────────────────────
# Switch to CosmosCheckpointStorage for durable persistence in production
# 生产环境可切换为 CosmosCheckpointStorage 实现持久化
storage = InMemoryCheckpointStorage()


# ── Wrapped steps | 包装的步骤 ───────────────────────────────────────
# step0 is cheap — no @step needed (always re-runs)
# step0 很轻量 — 不需要 @step（总是重新执行）

async def load_config() -> dict[str, Any]:
    """Step 0: Load config (cheap, no caching needed)."""
    return _step0_config()


@step
async def fetch_feeds(
    config: AppConfig, feeds: list, date_label: str, logger: logging.Logger,
) -> dict[str, Any]:
    """Step 1: Fetch RSS feeds — cached on resume to avoid re-fetching.
    抓取RSS源 — 恢复时使用缓存避免重复抓取。"""
    return _step1_fetch(config, feeds, date_label, logger)


@step
async def enrich_articles(
    config: AppConfig, articles: list, date_label: str, logger: logging.Logger,
) -> dict[str, Any]:
    """Step 2: Pre-score & enrich — cached to avoid duplicate LLM pre-scoring.
    预评分与充实 — 缓存以避免重复LLM预评分。"""
    return _step2_enrich(config, articles, date_label, logger)


@step
async def curate_stories(
    config: AppConfig, articles: list, date_label: str, logger: logging.Logger,
) -> dict[str, Any]:
    """Step 3: LLM curation — the most expensive step, always cache.
    LLM筛选 — 最昂贵的步骤，始终缓存。"""
    return _step3_curate(config, articles, date_label, logger)


@step
async def compose_html(
    config: AppConfig, stories: list, scanned_articles: list,
    date_label: str, logger: logging.Logger,
) -> dict[str, Any]:
    """Step 4: Compose newsletter HTML.
    组合新闻简报HTML。"""
    return _step4_compose(config, stories, scanned_articles, date_label, logger)


@step
async def send_email(
    config: AppConfig, recipients: list, subject: str,
    html_body: str, date_label: str, logger: logging.Logger,
) -> dict[str, Any]:
    """Step 5: Send email.
    发送邮件。"""
    return _step5_send(config, recipients, subject, html_body, date_label, logger)


# ── Summary helpers | 摘要辅助函数 ───────────────────────────────────

def _success_msg(article_count: int, stories: list, status: str) -> str:
    top = " | ".join(s.get("title", "") for s in stories[:3] if s.get("title"))
    imgs = sum(1 for s in stories if s.get("image_url"))
    return "✅ AI Weekly Digest v7 ready: %s articles, %s stories, %s images, top: %s, send: %s" % (
        article_count, len(stories), imgs, top or "n/a", status,
    )


def _fail_msg(message: str) -> str:
    return "❌ AI Weekly Digest failed: %s" % message[:350]


# ── The workflow | 工作流 ────────────────────────────────────────────

@workflow(checkpoint_storage=storage)
async def newsletter_pipeline(args_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Full newsletter pipeline as an Agent Framework workflow.
    完整的新闻简报流水线，以 Agent Framework 工作流形式运行。

    Each @step is checkpointed — on resume, completed steps return
    their saved result without re-execution.
    每个 @step 都有检查点 — 恢复时已完成的步骤直接返回保存的结果。
    """
    dry_run = args_dict.get("dry_run", False)
    to_override = args_dict.get("to")

    # ── Step 0: Config ───────────────────────────────────────────────
    ctx = await load_config()
    config = ctx["config"]
    feeds = ctx["feeds"]
    date_label = ctx["date_label"]
    logger = ctx["logger"]

    # ── Step 1: Fetch ────────────────────────────────────────────────
    fetch_out = await fetch_feeds(config, feeds, date_label, logger)

    if fetch_out["abort"]:
        msg = fetch_out["abort_message"]
        log_event(logger, logging.ERROR, "fetch_abort", message=msg)
        tg(_fail_msg(msg))
        return {"exit_code": 2, "error": msg}

    articles = fetch_out["articles"]
    failed_feeds = fetch_out["failed_feeds"]

    # ── Step 2: Enrich ───────────────────────────────────────────────
    enrich_out = await enrich_articles(config, articles, date_label, logger)

    # ── Step 3: Curate ───────────────────────────────────────────────
    curate_out = await curate_stories(config, enrich_out["articles"], date_label, logger)
    stories = curate_out["stories"]
    llm_failed = curate_out["llm_failed"]

    # ── Step 4: Compose ──────────────────────────────────────────────
    compose_out = await compose_html(config, stories, articles, date_label, logger)
    html_body = compose_out["html_body"]

    if dry_run:
        tg(_success_msg(len(articles), stories, "dry-run"))
        print("\n--- Pipeline finished (dry-run mode, email skipped) ---")
        code = 2 if llm_failed else (1 if failed_feeds else 0)
        return {"exit_code": code, "status": "dry-run", "stories": len(stories)}

    # ── Step 5: Send ─────────────────────────────────────────────────
    if to_override and to_override.strip():
        recipients = [r.strip() for r in to_override.split(",") if r.strip()]
    else:
        recipients = list(config.recipients)

    subject = "🤖 AI Weekly Digest — Week of %s [Issue #%s]" % (
        week_range_label(window_days=config.fetch_window_days),
        config.issue_number,
    )
    send_out = await send_email(config, recipients, subject, html_body, date_label, logger)

    if not send_out["success"]:
        tg(_fail_msg(send_out["detail"]))
        return {"exit_code": 2, "error": send_out["detail"]}

    tg(_success_msg(len(articles), stories, send_out["detail"]))
    print("\n--- Pipeline finished successfully ---")
    code = 2 if llm_failed else (1 if failed_feeds else 0)
    return {"exit_code": code, "status": "ok", "stories": len(stories)}


# ── CLI | 命令行 ────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Weekly Digest — Agent Framework workflow")
    parser.add_argument("--dry-run", action="store_true", help="Skip email sending")
    parser.add_argument("--to", help="Override recipient email(s), comma-separated")
    parser.add_argument("--stream", action="store_true", help="Stream workflow events to console")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    print("=" * 60)
    print("  AI Weekly Digest — Agent Framework Workflow")
    print("=" * 60)
    print()

    args_dict = {"dry_run": args.dry_run, "to": args.to}

    if args.stream:
        # Stream mode: print events as they happen
        # 流式模式：实时打印事件
        result = await newsletter_pipeline.run(args_dict, stream=True)
        async for event in result:
            if event.type in ("executor_invoked", "executor_completed"):
                print("  [event] %s: %s" % (event.type, event.executor_id))
        output = result.get_outputs()[0]
    else:
        result = await newsletter_pipeline.run(args_dict)
        output = result.get_outputs()[0]

    print("\nResult: %s" % output)
    return output.get("exit_code", 0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
