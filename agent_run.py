#!/usr/bin/env python3
"""
AI Weekly Digest — Agent Framework workflow entry point.
AI 周刊摘要 — Agent Framework 工作流入口。

Uses Microsoft Agent Framework's Executor + WorkflowBuilder API
to orchestrate the 5-step newsletter pipeline with:
使用 Microsoft Agent Framework 的 Executor + WorkflowBuilder API 编排5步流水线：

  - Built-in observability via Agent Inspector
    通过 Agent Inspector 提供内置可观测性
  - HTTP server mode for AI Toolkit playground
    HTTP 服务器模式用于 AI Toolkit playground
  - CLI mode for command-line execution
    CLI 模式用于命令行执行

Usage | 用法:
    python agent_run.py                         # HTTP server (Agent Inspector) | HTTP服务器模式
    python agent_run.py --server                # same as above | 同上
    python agent_run.py --cli                   # CLI mode full pipeline | CLI模式完整流水线
    python agent_run.py --cli --dry-run         # CLI skip send | CLI跳过发送
    python agent_run.py --cli --to user@x.com   # CLI override recipient | CLI覆盖收件人
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

from agent_framework import (
    Executor, handler, Message, WorkflowBuilder,
    AgentResponseUpdate, Content, WorkflowContext,
    register_state_type,
)
from agent_framework.observability import configure_otel_providers
from pydantic import BaseModel, Field

# Enable multi-agent visualization in VS Code Microsoft Foundry extension
# 启用 VS Code Microsoft Foundry 扩展的多 Agent 可视化
# OTLP gRPC endpoint: http://localhost:4319
# Gracefully skipped in CI where opentelemetry-exporter-otlp-proto-grpc is not installed
# 在 CI 环境中若未安装 opentelemetry 导出器则静默跳过
try:
    configure_otel_providers(
        vs_code_extension_port=4319,
        enable_sensitive_data=True,
    )
except ImportError:
    pass

from core.utils import (
    log_event,
    tg,
    week_range_label,
)

# Import the existing step functions (sync)
# 导入现有的同步步骤函数
from steps.step0_config import run as _step0_config
from steps.step1_fetch import run as _step1_fetch
from steps.step2_enrich import run as _step2_enrich
from steps.step3_curate import run as _step3_curate
from steps.step4_compose import run as _step4_compose
from steps.step5_send import run as _step5_send

from dataclasses import dataclass, field


# ── Shared workflow state | 共享工作流状态 ───────────────────────────

@dataclass
class PipelineState:
    """Shared state passed between workflow executors via edges.
    通过边在工作流 executor 之间传递的共享状态。"""
    config: Any = None
    feeds: list = field(default_factory=list)
    date_label: str = ""
    logger: Any = None
    articles: list = field(default_factory=list)
    stories: list = field(default_factory=list)
    curate_meta: dict = field(default_factory=dict)
    html_body: str = ""
    dry_run: bool = False
    to_override: str | None = None
    error: str | None = None

register_state_type(PipelineState)


# ── Summary helpers | 摘要辅助函数 ───────────────────────────────────

def _success_msg(article_count: int, stories: list, status: str) -> str:
    top = " | ".join(s.get("title", "") for s in stories[:3] if s.get("title"))
    imgs = sum(1 for s in stories if s.get("image_url"))
    return "✅ AI Weekly Digest v7 ready: %s articles, %s stories, %s images, top: %s, send: %s" % (
        article_count, len(stories), imgs, top or "n/a", status,
    )


def _fail_msg(message: str) -> str:
    return "❌ AI Weekly Digest failed: %s" % message[:350]


# ── Step Executors | 步骤执行器 ──────────────────────────────────────
# Each step is an independent Executor node in the workflow graph.
# 每个步骤是工作流图中的独立 Executor 节点。

class WorkflowInput(BaseModel):
    """Input for the newsletter workflow. All fields have defaults — just click Run.
    新闻简报工作流的输入。所有字段都有默认值 — 直接点 Run 即可。"""

    dry_run: bool = Field(default=False, description="Skip email sending (跳过发送邮件)")


class ConfigLoader(Executor):
    """Step 0: Load configuration and feeds.
    步骤0: 加载配置和 feeds。"""

    async def _run(self, dry_run: bool, ctx: WorkflowContext[PipelineState]) -> None:
        await ctx.yield_output(AgentResponseUpdate(
            contents=[Content("text", text="⚙️ Step 0: Loading configuration…")],
            role="assistant", author_name=self.id,
        ))

        result = await asyncio.to_thread(_step0_config)
        state = PipelineState(
            config=result["config"],
            feeds=result["feeds"],
            date_label=result["date_label"],
            logger=result["logger"],
            dry_run=dry_run,
        )
        await ctx.send_message(state)

    @handler
    async def handle(self, input: WorkflowInput, ctx: WorkflowContext[PipelineState]) -> None:
        await self._run(input.dry_run, ctx)


class FeedFetcher(Executor):
    """Step 1: Fetch RSS feeds.
    步骤1: 抓取 RSS feeds。"""

    @handler(input=PipelineState)
    async def handle(self, data: PipelineState, ctx: WorkflowContext[PipelineState]) -> None:
        await ctx.yield_output(AgentResponseUpdate(
            contents=[Content("text", text="📡 Step 1: Fetching RSS feeds…")],
            role="assistant", author_name=self.id,
        ))

        fetch_out = await asyncio.to_thread(
            _step1_fetch, data.config, data.feeds, data.date_label, data.logger
        )

        if fetch_out["abort"]:
            data.error = fetch_out["abort_message"]
            log_event(data.logger, logging.ERROR, "fetch_abort", message=data.error)
            await ctx.yield_output(AgentResponseUpdate(
                contents=[Content("text", text=_fail_msg(data.error))],
                role="assistant", author_name=self.id,
            ))
            return

        data.articles = fetch_out["articles"]

        await ctx.yield_output(AgentResponseUpdate(
            contents=[Content("text", text="📡 Fetched %d articles" % len(data.articles))],
            role="assistant", author_name=self.id,
        ))
        await ctx.send_message(data)


class ArticleEnricher(Executor):
    """Step 2: Pre-score & enrich articles.
    步骤2: 预评分和充实文章。"""

    @handler(input=PipelineState)
    async def handle(self, data: PipelineState, ctx: WorkflowContext[PipelineState]) -> None:
        await ctx.yield_output(AgentResponseUpdate(
            contents=[Content("text", text="🔍 Step 2: Enriching %d articles…" % len(data.articles))],
            role="assistant", author_name=self.id,
        ))

        enrich_out = await asyncio.to_thread(
            _step2_enrich, data.config, data.articles, data.date_label, data.logger
        )
        data.articles = enrich_out["articles"]
        await ctx.send_message(data)


class StoryCurator(Executor):
    """Step 3: LLM curation — select top stories.
    步骤3: LLM 筛选 — 选出最佳故事。"""

    @handler(input=PipelineState)
    async def handle(self, data: PipelineState, ctx: WorkflowContext[PipelineState]) -> None:
        await ctx.yield_output(AgentResponseUpdate(
            contents=[Content("text", text="🤖 Step 3: Curating stories with LLM…")],
            role="assistant", author_name=self.id,
        ))

        curate_out = await asyncio.to_thread(
            _step3_curate, data.config, data.articles, data.date_label, data.logger
        )
        data.stories = curate_out["stories"]
        data.curate_meta = curate_out.get("meta", {}) or {}

        await ctx.yield_output(AgentResponseUpdate(
            contents=[Content("text", text="🤖 Curated %d stories" % len(data.stories))],
            role="assistant", author_name=self.id,
        ))
        await ctx.send_message(data)


class HtmlComposer(Executor):
    """Step 4: Compose newsletter HTML.
    步骤4: 组合新闻简报 HTML。"""

    @handler(input=PipelineState)
    async def handle(self, data: PipelineState, ctx: WorkflowContext[PipelineState]) -> None:
        await ctx.yield_output(AgentResponseUpdate(
            contents=[Content("text", text="📝 Step 4: Composing HTML newsletter…")],
            role="assistant", author_name=self.id,
        ))

        compose_out = await asyncio.to_thread(
            _step4_compose, data.config, data.stories, data.articles, data.date_label, data.logger, data.curate_meta
        )
        data.html_body = compose_out["html_body"]

        if data.dry_run:
            tg(_success_msg(len(data.articles), data.stories, "dry-run"))
            await ctx.yield_output(AgentResponseUpdate(
                contents=[Content("text", text=_success_msg(len(data.articles), data.stories, "dry-run"))],
                role="assistant", author_name=self.id,
            ))
            return

        await ctx.send_message(data)


class EmailSender(Executor):
    """Step 5: Send newsletter email.
    步骤5: 发送新闻简报邮件。"""

    @handler(input=PipelineState)
    async def handle(self, data: PipelineState, ctx: WorkflowContext[PipelineState]) -> None:
        await ctx.yield_output(AgentResponseUpdate(
            contents=[Content("text", text="📧 Step 5: Sending email…")],
            role="assistant", author_name=self.id,
        ))

        if data.to_override and data.to_override.strip():
            recipients = [r.strip() for r in data.to_override.split(",") if r.strip()]
        else:
            recipients = list(data.config.recipients)

        subject = "AI Weekly Digest — Week of %s" % (
            week_range_label(window_days=data.config.fetch_window_days),
        )

        send_out = await asyncio.to_thread(
            _step5_send, data.config, recipients, subject, data.html_body, data.date_label, data.logger
        )

        if not send_out["success"]:
            tg(_fail_msg(send_out["detail"]))
            await ctx.yield_output(AgentResponseUpdate(
                contents=[Content("text", text=_fail_msg(send_out["detail"]))],
                role="assistant", author_name=self.id,
            ))
            return

        tg(_success_msg(len(data.articles), data.stories, send_out["detail"]))
        await ctx.yield_output(AgentResponseUpdate(
            contents=[Content("text", text=_success_msg(len(data.articles), data.stories, send_out["detail"]))],
            role="assistant", author_name=self.id,
        ))


# ── Build multi-step workflow | 构建多步骤工作流 ────────────────────
# Each executor is a visible node in the Foundry Visualizer.
# 每个 executor 在 Foundry Visualizer 中是一个可见节点。

_config_loader = ConfigLoader(id="0-config-loader")
_feed_fetcher = FeedFetcher(id="1-feed-fetcher")
_article_enricher = ArticleEnricher(id="2-article-enricher")
_story_curator = StoryCurator(id="3-story-curator")
_html_composer = HtmlComposer(id="4-html-composer")
_email_sender = EmailSender(id="5-email-sender")

newsletter_workflow = (
    WorkflowBuilder(start_executor=_config_loader)
    .add_edge(_config_loader, _feed_fetcher)
    .add_edge(_feed_fetcher, _article_enricher)
    .add_edge(_article_enricher, _story_curator)
    .add_edge(_story_curator, _html_composer)
    .add_edge(_html_composer, _email_sender)
    .build()
)


# ── CLI | 命令行 ────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Weekly Digest — Agent Framework workflow")
    parser.add_argument("--server", action="store_true", default=True,
                        help="Run as HTTP server for Agent Inspector (default)")
    parser.add_argument("--cli", action="store_true",
                        help="Run in CLI mode instead of HTTP server")
    parser.add_argument("--dry-run", action="store_true", help="Skip email sending (CLI mode)")
    parser.add_argument("--to", help="Override recipient email(s), comma-separated (CLI mode)")
    return parser.parse_args()


async def run_server() -> None:
    """Start the agent as an HTTP server for AI Toolkit Agent Inspector.
    启动 agent 作为 HTTP 服务器，用于 AI Toolkit Agent Inspector。"""
    from azure.ai.agentserver.agentframework import from_agent_framework

    print("=" * 60)
    print("  AI Weekly Digest — HTTP Server Mode (Agent Inspector)")
    print("=" * 60)
    print()
    agent = newsletter_workflow.as_agent()
    await from_agent_framework(agent).run_async()


async def run_cli(args: argparse.Namespace) -> int:
    """Original CLI pipeline mode.
    原始 CLI 流水线模式。"""
    print("=" * 60)
    print("  AI Weekly Digest — CLI Mode")
    print("=" * 60)
    print()

    # Step 0: Config
    ctx = _step0_config()
    config, feeds, date_label, logger = ctx["config"], ctx["feeds"], ctx["date_label"], ctx["logger"]

    # Step 1: Fetch
    fetch_out = _step1_fetch(config, feeds, date_label, logger)
    if fetch_out["abort"]:
        msg = fetch_out["abort_message"]
        log_event(logger, logging.ERROR, "fetch_abort", message=msg)
        print(_fail_msg(msg))
        return 2
    articles = fetch_out["articles"]

    # Step 2: Enrich
    enrich_out = _step2_enrich(config, articles, date_label, logger)

    # Step 3: Curate
    curate_out = _step3_curate(config, enrich_out["articles"], date_label, logger)
    stories = curate_out["stories"]
    curate_meta = curate_out.get("meta", {}) or {}

    # Step 4: Compose
    compose_out = _step4_compose(config, stories, articles, date_label, logger, meta=curate_meta)
    html_body = compose_out["html_body"]

    if args.dry_run:
        print(_success_msg(len(articles), stories, "dry-run"))
        return 0

    # Step 5: Send
    if args.to and args.to.strip():
        recipients = [r.strip() for r in args.to.split(",") if r.strip()]
    else:
        recipients = list(config.recipients)

    subject = "AI Weekly Digest — Week of %s" % (
        week_range_label(window_days=config.fetch_window_days),
    )
    send_out = _step5_send(config, recipients, subject, html_body, date_label, logger)

    if not send_out["success"]:
        print(_fail_msg(send_out["detail"]))
        return 2

    print(_success_msg(len(articles), stories, send_out["detail"]))
    return 0


async def main() -> int:
    args = parse_args()

    if args.cli:
        return await run_cli(args)

    # Default: HTTP server mode for Agent Inspector
    await run_server()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
