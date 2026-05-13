#!/usr/bin/env python3
"""
AI Weekly Digest — Workflow definition (shared by CLI & DevUI).
AI 周刊摘要 — 工作流定义（CLI 和 DevUI 共用）。

This module defines the Executor classes, shared state, and workflow graph.
Both agent_run.py (CLI) and devui_run.py (DevUI) import from here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from agent_framework import (
    Executor, handler, WorkflowBuilder,
    AgentResponseUpdate, Content, WorkflowContext,
    register_state_type, InMemoryCheckpointStorage,
    WorkflowViz,
)
from pydantic import BaseModel, Field

from core.utils import (
    log_event,
    tg,
    week_range_label,
)

from steps.step0_config import run as _step0_config
from steps.step1_fetch import run as _step1_fetch
from steps.step2_enrich import run as _step2_enrich
from steps.step3_curate import run as _step3_curate
from steps.step4_compose import run as _step4_compose
from steps.step5_send import run as _step5_send


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


# ── Workflow input (Pydantic model for DevUI form) ───────────────

class WorkflowInput(BaseModel):
    """Input for the newsletter workflow. All fields have defaults — just click Run.
    新闻简报工作流的输入。所有字段都有默认值 — 直接点 Run 即可。"""

    dry_run: bool = Field(default=False, description="Skip email sending (跳过发送邮件)")
    to_override: str = Field(default="", description="Override recipient email(s), comma-separated (覆盖收件人)")


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

class ConfigLoader(Executor):
    """Step 0: Load configuration and feeds.
    步骤0: 加载配置和 feeds。"""

    async def _run(self, dry_run: bool, to_override: str, ctx: WorkflowContext[PipelineState]) -> None:
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
            to_override=to_override or None,
        )
        await ctx.send_message(state)

    @handler
    async def handle(self, input: WorkflowInput, ctx: WorkflowContext[PipelineState]) -> None:
        await self._run(input.dry_run, input.to_override, ctx)


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


# ── Build workflow | 构建工作流 ──────────────────────────────────────

_config_loader = ConfigLoader(id="0-config-loader")
_feed_fetcher = FeedFetcher(id="1-feed-fetcher")
_article_enricher = ArticleEnricher(id="2-article-enricher")
_story_curator = StoryCurator(id="3-story-curator")
_html_composer = HtmlComposer(id="4-html-composer")
_email_sender = EmailSender(id="5-email-sender")


def build_workflow(checkpoint_storage: InMemoryCheckpointStorage | None = None):
    """Build (or rebuild) the workflow. A fresh instance is needed for each checkpoint resume.
    构建（或重建）工作流。每次 checkpoint 恢复都需要一个新实例。"""
    return (
        WorkflowBuilder(
            name="ai-weekly-digest",
            start_executor=_config_loader,
            checkpoint_storage=checkpoint_storage,
        )
        .add_edge(_config_loader, _feed_fetcher)
        .add_edge(_feed_fetcher, _article_enricher)
        .add_edge(_article_enricher, _story_curator)
        .add_edge(_story_curator, _html_composer)
        .add_edge(_html_composer, _email_sender)
        .build()
    )


# Default instance (no checkpointing) — used by DevUI
# 默认实例（无 checkpoint）— DevUI 使用
newsletter_workflow = build_workflow()


# ── Visualization | 可视化 ───────────────────────────────────────────

if __name__ == "__main__":
    viz = WorkflowViz(newsletter_workflow)
    mermaid_str = viz.to_mermaid()

    print("Mermaid:\n=======")
    print(mermaid_str)
    print("=======")

    print("\nDiGraph:\n=======")
    print(viz.to_digraph(include_internal_executors=True))
    print("=======")

    try:
        import pathlib, shutil
        svg_tmp = viz.export(format="svg")
        svg_dest = pathlib.Path(__file__).with_name("workflow_viz.svg")
        shutil.move(svg_tmp, svg_dest)
        print(f"\nSVG exported to: {svg_dest}")
    except Exception:
        print("\n(SVG export needs `apt install graphviz` — copy the Mermaid text above to https://mermaid.live)")
