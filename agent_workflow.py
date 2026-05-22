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
from dataclasses import asdict, dataclass, field
from typing import Any

from agent_framework import (
    Executor,
    handler,
    WorkflowBuilder,
    AgentResponseUpdate,
    Content,
    WorkflowContext,
    register_state_type,
    InMemoryCheckpointStorage,
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


@dataclass
class LocaleTranslation:
    """Per-locale translation result emitted by TranslateLocale → LocaleAssembler.
    单个语言的翻译结果消息，由 TranslateLocale 发送给 LocaleAssembler。

    status="ok"    → stories populated with translated dicts.
    status="error" → stories empty, error populated; assembler logs + skips this locale.
    """

    locale: str
    status: str
    stories: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass
class TranslateTrigger:
    """Zero-field sentinel emitted by HtmlComposer to fan out to every TranslateLocale.
    零字段哨兵：HtmlComposer 发出，扇出到每个 TranslateLocale。"""

    pass


# ── Shared-state keys | 共享状态键 ────────────────────────────────────
# Use these constants with ctx.set_state(key, value) / ctx.get_state(key, default)
# (the methods are synchronous — do NOT await them).
SS_EN_HTML = "compose.en_html"
SS_STORIES = "compose.stories"
SS_SCANNED = "compose.scanned_articles"
SS_DATE_LABEL = "compose.date_label"
SS_META = "compose.meta"
SS_DRY_RUN = "pipeline.dry_run"
SS_TO_OVERRIDE = "pipeline.to_override"
SS_CONFIG = "pipeline.config"
SS_FINAL_HTML = "compose.final_html"


register_state_type(PipelineState)


# ── Workflow input (Pydantic model for DevUI form) ───────────────


class WorkflowInput(BaseModel):
    """Input for the newsletter workflow. All fields have defaults — just click Run.
    新闻简报工作流的输入。所有字段都有默认值 — 直接点 Run 即可。"""

    dry_run: bool = Field(
        default=False, description="Skip email sending (跳过发送邮件)"
    )
    to_override: str = Field(
        default="",
        description="Override recipient email(s), comma-separated (覆盖收件人)",
    )
    languages: list[str] | None = Field(
        default=None,
        description=(
            "Override config.compose_languages at runtime. None = use config.yaml; "
            '[] = force EN-only; ["zh","ko"] = fan-out to those locales. '
            "(运行时覆盖 config.compose_languages)"
        ),
    )


# ── Summary helpers | 摘要辅助函数 ───────────────────────────────────


def _success_msg(article_count: int, stories: list, status: str) -> str:
    top = " | ".join(s.get("title", "") for s in stories[:3] if s.get("title"))
    imgs = sum(1 for s in stories if s.get("image_url"))
    return (
        "✅ AI Weekly Digest v7 ready: %s articles, %s stories, %s images, top: %s, send: %s"
        % (
            article_count,
            len(stories),
            imgs,
            top or "n/a",
            status,
        )
    )


def _fail_msg(message: str) -> str:
    return "❌ AI Weekly Digest failed: %s" % message[:350]


# ── Step Executors | 步骤执行器 ──────────────────────────────────────


class ConfigLoader(Executor):
    """Step 0: Load configuration and feeds.
    步骤0: 加载配置和 feeds。"""

    async def _run(
        self,
        dry_run: bool,
        to_override: str,
        languages_override: list[str] | None,
        ctx: WorkflowContext[PipelineState],
    ) -> None:
        await ctx.yield_output(
            AgentResponseUpdate(
                contents=[Content("text", text="⚙️ Step 0: Loading configuration…")],
                role="assistant",
                author_name=self.id,
            )
        )

        result = await asyncio.to_thread(_step0_config)
        config = result["config"]
        if languages_override is not None:
            config.compose_languages = list(languages_override)
        state = PipelineState(
            config=config,
            feeds=result["feeds"],
            date_label=result["date_label"],
            logger=result["logger"],
            dry_run=dry_run,
            to_override=to_override or None,
        )
        await ctx.send_message(state)

    @handler
    async def handle(
        self, input: WorkflowInput, ctx: WorkflowContext[PipelineState]
    ) -> None:
        await self._run(input.dry_run, input.to_override, input.languages, ctx)


class FeedFetcher(Executor):
    """Step 1: Fetch RSS feeds.
    步骤1: 抓取 RSS feeds。"""

    @handler(input=PipelineState)
    async def handle(
        self, data: PipelineState, ctx: WorkflowContext[PipelineState]
    ) -> None:
        await ctx.yield_output(
            AgentResponseUpdate(
                contents=[Content("text", text="📡 Step 1: Fetching RSS feeds…")],
                role="assistant",
                author_name=self.id,
            )
        )

        fetch_out = await asyncio.to_thread(
            _step1_fetch, data.config, data.feeds, data.date_label, data.logger
        )

        if fetch_out["abort"]:
            data.error = fetch_out["abort_message"]
            log_event(data.logger, logging.ERROR, "fetch_abort", message=data.error)
            await ctx.yield_output(
                AgentResponseUpdate(
                    contents=[Content("text", text=_fail_msg(data.error))],
                    role="assistant",
                    author_name=self.id,
                )
            )
            return

        data.articles = fetch_out["articles"]

        await ctx.yield_output(
            AgentResponseUpdate(
                contents=[
                    Content("text", text="📡 Fetched %d articles" % len(data.articles))
                ],
                role="assistant",
                author_name=self.id,
            )
        )
        await ctx.send_message(data)


class ArticleEnricher(Executor):
    """Step 2: Pre-score & enrich articles.
    步骤2: 预评分和充实文章。"""

    @handler(input=PipelineState)
    async def handle(
        self, data: PipelineState, ctx: WorkflowContext[PipelineState]
    ) -> None:
        await ctx.yield_output(
            AgentResponseUpdate(
                contents=[
                    Content(
                        "text",
                        text="🔍 Step 2: Enriching %d articles…" % len(data.articles),
                    )
                ],
                role="assistant",
                author_name=self.id,
            )
        )

        enrich_out = await asyncio.to_thread(
            _step2_enrich, data.config, data.articles, data.date_label, data.logger
        )
        data.articles = enrich_out["articles"]
        await ctx.send_message(data)


class StoryCurator(Executor):
    """Step 3: LLM curation — select top stories.
    步骤3: LLM 筛选 — 选出最佳故事。"""

    @handler(input=PipelineState)
    async def handle(
        self, data: PipelineState, ctx: WorkflowContext[PipelineState]
    ) -> None:
        await ctx.yield_output(
            AgentResponseUpdate(
                contents=[
                    Content("text", text="🤖 Step 3: Curating stories with LLM…")
                ],
                role="assistant",
                author_name=self.id,
            )
        )

        curate_out = await asyncio.to_thread(
            _step3_curate, data.config, data.articles, data.date_label, data.logger
        )
        data.stories = curate_out["stories"]
        data.curate_meta = curate_out.get("meta", {}) or {}

        await ctx.yield_output(
            AgentResponseUpdate(
                contents=[
                    Content("text", text="🤖 Curated %d stories" % len(data.stories))
                ],
                role="assistant",
                author_name=self.id,
            )
        )
        await ctx.send_message(data)


class HtmlComposer(Executor):
    """Step 4: Compose newsletter HTML.
    步骤4: 组合新闻简报 HTML。

    Renders the EN body up-front and decides between two downstream shapes
    based on ``config.compose_languages``:

    * **Empty** (legacy / no translations requested) — populates
      ``data.html_body`` with the EN HTML, runs the dry-run short-circuit
      here, then forwards ``PipelineState`` directly to ``EmailSender``.

    * **Non-empty** — writes EN HTML + shared context to ``ctx.set_state``
      (``SS_EN_HTML``, ``SS_STORIES``, ``SS_SCANNED``, ``SS_DATE_LABEL``,
      ``SS_META``, ``SS_DRY_RUN``, ``SS_TO_OVERRIDE``, ``SS_CONFIG``) so
      every fan-out target sees the same snapshot, then emits a single
      zero-field :class:`TranslateTrigger`. agent-framework dispatches it
      to every ``TranslateLocale`` wired via ``add_fan_out_edges``; each
      locale's result later reaches :class:`LocaleAssembler`, which owns
      the dry-run short-circuit on the multilingual branch."""

    @handler(input=PipelineState, output=PipelineState | TranslateTrigger)
    async def handle(
        self,
        data: PipelineState,
        ctx: WorkflowContext[PipelineState | TranslateTrigger],
    ) -> None:
        await ctx.yield_output(
            AgentResponseUpdate(
                contents=[
                    Content("text", text="📝 Step 4: Composing HTML newsletter…")
                ],
                role="assistant",
                author_name=self.id,
            )
        )

        languages = list(getattr(data.config, "compose_languages", []) or [])

        en_compose_out = await asyncio.to_thread(
            lambda: _step4_compose(
                data.config,
                data.stories,
                data.articles,
                data.date_label,
                data.logger,
                meta=data.curate_meta,
                languages=[],
            )
        )
        en_html = en_compose_out["html_body"]

        if not languages:
            data.html_body = en_html

            if data.dry_run:
                tg(_success_msg(len(data.articles), data.stories, "dry-run"))
                await ctx.yield_output(
                    AgentResponseUpdate(
                        contents=[
                            Content(
                                "text",
                                text=_success_msg(
                                    len(data.articles), data.stories, "dry-run"
                                ),
                            )
                        ],
                        role="assistant",
                        author_name=self.id,
                    )
                )
                return

            await ctx.send_message(data)
            return

        ctx.set_state(SS_EN_HTML, en_html)
        ctx.set_state(SS_STORIES, data.stories)
        ctx.set_state(SS_SCANNED, [asdict(a) for a in data.articles])
        ctx.set_state(SS_DATE_LABEL, data.date_label)
        ctx.set_state(SS_META, data.curate_meta)
        ctx.set_state(SS_DRY_RUN, data.dry_run)
        ctx.set_state(SS_TO_OVERRIDE, data.to_override)
        ctx.set_state(SS_CONFIG, data.config)

        await ctx.send_message(TranslateTrigger())


class TranslateLocale(Executor):
    """Step 4b: Translate curated stories for a single non-English locale.
    步骤 4b: 为单个非英语 locale 翻译策划后的故事。

    Each instance handles ONE locale (e.g. ``4b-translate-zh``) so that DevUI
    renders one visible node per language and a single locale's failure
    cannot poison the others — the EN newsletter always ships (see issue #28).

    Receives a zero-field :class:`TranslateTrigger` (fan-out from
    :class:`HtmlComposer`); reads ``config`` + ``stories`` from shared state
    via the SYNC ``ctx.get_state`` API; runs the blocking Translator call in
    a worker thread; emits exactly one :class:`LocaleTranslation` (status
    ``"ok"`` on success, ``"error"`` on any non-cancellation exception)."""

    def __init__(self, locale: str) -> None:
        super().__init__(id=f"4b-translate-{locale}")
        self._locale = locale

    @handler
    async def handle(
        self,
        _trigger: TranslateTrigger,
        ctx: WorkflowContext[LocaleTranslation],
    ) -> None:
        # Local imports keep module-load light + avoid circular import with
        # core.html_composer (which imports from agent_framework on its own).
        from core.translator import Translator, LocaleConfig
        from core.llm_client import LlmClient

        # ctx.get_state is SYNC in agent-framework ≥1.2 — do NOT await.
        config = ctx.get_state(SS_CONFIG)
        stories = ctx.get_state(SS_STORIES, []) or []
        logger = logging.getLogger("ai-newsletter-v5")

        try:
            factory = getattr(LocaleConfig, self._locale, None)
            if factory is None:
                # Unknown locale — surface as a clean per-locale error so the
                # assembler still drops it without breaking the workflow.
                raise ValueError(f"unknown locale: {self._locale}")
            locale_cfg = factory()

            translator = Translator(
                llm_client=LlmClient(config, logger),
                prompt_version=getattr(config, "translate_prompt_version", "v1"),
                logger=logger,
                locale=locale_cfg,
            )
            translated = await asyncio.to_thread(translator.translate_stories, stories)
            await ctx.send_message(
                LocaleTranslation(locale=self._locale, status="ok", stories=translated)
            )
        except asyncio.CancelledError:
            # Cooperative cancellation must propagate unchanged.
            raise
        except Exception as exc:  # noqa: BLE001 — isolation is the whole point
            logger.warning("translate failed locale=%s reason=%s", self._locale, exc)
            await ctx.send_message(
                LocaleTranslation(
                    locale=self._locale,
                    status="error",
                    stories=[],
                    error=str(exc),
                )
            )


class LocaleAssembler(Executor):
    """Step 4z: Fan-in target. Merge per-locale translations into final HTML.
    步骤 4z: 扇入目标。把每个语言的翻译合并成最终 HTML。

    Receives ``list[LocaleTranslation]`` (delivered exactly once after EVERY
    upstream ``TranslateLocale`` produces — agent-framework superstep
    barrier). Reads EN HTML + scanned articles + meta from shared state,
    drops errored locales (logging them to DevUI for visibility), sorts OK
    locales by ``config.compose_languages`` order, splices each locale's
    section into the EN HTML in ONE call (preserves
    ``test_v8_bilingual.test_footer_marker_count`` invariant), then re-emits
    a :class:`PipelineState` carrying ``html_body=final_html`` so that
    :class:`EmailSender` (already wired to consume ``PipelineState``) needs
    no changes.

    Also takes over :class:`HtmlComposer`'s old dry-run short-circuit: when
    ``dry_run=True`` the assembler logs the success message and stops
    instead of forwarding to the email sender."""

    def __init__(self) -> None:
        super().__init__(id="4z-locale-assembler")

    @handler
    async def handle(
        self,
        payloads: list[LocaleTranslation],
        ctx: WorkflowContext[PipelineState],
    ) -> None:
        from core.html_composer import HtmlComposer as _RendererHtmlComposer
        from core.models import Article

        logger = logging.getLogger("ai-newsletter-v5")

        # SYNC reads — see TranslateLocale.
        config = ctx.get_state(SS_CONFIG)
        en_html = ctx.get_state(SS_EN_HTML, "") or ""
        scanned_raw = ctx.get_state(SS_SCANNED, []) or []
        date_label = ctx.get_state(SS_DATE_LABEL, "") or ""
        meta = ctx.get_state(SS_META, {}) or {}
        dry_run = bool(ctx.get_state(SS_DRY_RUN, False))
        to_override = ctx.get_state(SS_TO_OVERRIDE, None)
        stories = ctx.get_state(SS_STORIES, []) or []

        # Reconstruct Article dataclasses from the asdict() snapshots that
        # HtmlComposer stashed (shared-state values must be plain data).
        scanned_articles = [Article(**a) for a in scanned_raw]

        # 1) Surface per-locale errors for DevUI + structured log (visibility,
        #    not failure — EN newsletter still ships).
        ok: list[LocaleTranslation] = []
        err_locales: list[str] = []
        for p in payloads:
            if p.status == "ok" and p.stories:
                ok.append(p)
            else:
                err_locales.append(p.locale)
                await ctx.yield_output(
                    AgentResponseUpdate(
                        contents=[
                            Content(
                                "text",
                                text=(
                                    f"⚠️ Translation skipped: locale={p.locale} "
                                    f"reason={p.error or 'empty result'}"
                                ),
                            )
                        ],
                        role="assistant",
                        author_name=self.id,
                    )
                )
                logger.warning(
                    "locale_skipped locale=%s reason=%s",
                    p.locale,
                    p.error or "empty result",
                )

        # 2) Sort OK locales by the config-declared order (Oracle Q6).
        config_order = list(getattr(config, "compose_languages", []) or [])
        ok.sort(
            key=lambda p: (
                config_order.index(p.locale) if p.locale in config_order else 99
            )
        )

        # 3) Build final HTML. Empty `ok` ⇒ EN ships as-is (NOT an error).
        if not ok:
            final_html = en_html
        else:
            renderer = _RendererHtmlComposer(config)
            sections: list[str] = []
            for p in ok:
                sections.append(
                    renderer._compose_locale_section(
                        p.locale,
                        p.stories,
                        scanned_articles,
                        date_label,
                        meta,
                    )
                )
            # ONE splice call — preserves the single-footer-marker invariant
            # asserted by tests/test_v8_bilingual.test_footer_marker_count.
            final_html = _RendererHtmlComposer._splice_locale_sections(
                en_html, sections
            )

        ctx.set_state(SS_FINAL_HTML, final_html)
        logger.info(
            "assembler_done ok_locales=%s err_locales=%s",
            [p.locale for p in ok],
            err_locales,
        )

        # 4) Rebuild PipelineState for the downstream EmailSender. The dry-run
        #    short-circuit (previously in HtmlComposer) now lives here because
        #    HtmlComposer no longer owns the final HTML.
        state = PipelineState(
            config=config,
            articles=scanned_articles,
            stories=stories,
            date_label=date_label,
            logger=logger,
            html_body=final_html,
            dry_run=dry_run,
            to_override=to_override,
        )

        if dry_run:
            tg(_success_msg(len(scanned_articles), stories, "dry-run"))
            await ctx.yield_output(
                AgentResponseUpdate(
                    contents=[
                        Content(
                            "text",
                            text=_success_msg(
                                len(scanned_articles), stories, "dry-run"
                            ),
                        )
                    ],
                    role="assistant",
                    author_name=self.id,
                )
            )
            return

        await ctx.send_message(state)


class EmailSender(Executor):
    """Step 5: Send newsletter email.
    步骤5: 发送新闻简报邮件。"""

    @handler(input=PipelineState)
    async def handle(
        self, data: PipelineState, ctx: WorkflowContext[PipelineState]
    ) -> None:
        await ctx.yield_output(
            AgentResponseUpdate(
                contents=[Content("text", text="📧 Step 5: Sending email…")],
                role="assistant",
                author_name=self.id,
            )
        )

        if data.to_override and data.to_override.strip():
            recipients = [r.strip() for r in data.to_override.split(",") if r.strip()]
        else:
            recipients = list(data.config.recipients)

        subject = "AI Weekly Digest — Week of %s" % (
            week_range_label(window_days=data.config.fetch_window_days),
        )

        send_out = await asyncio.to_thread(
            _step5_send,
            data.config,
            recipients,
            subject,
            data.html_body,
            data.date_label,
            data.logger,
        )

        if not send_out["success"]:
            tg(_fail_msg(send_out["detail"]))
            await ctx.yield_output(
                AgentResponseUpdate(
                    contents=[Content("text", text=_fail_msg(send_out["detail"]))],
                    role="assistant",
                    author_name=self.id,
                )
            )
            return

        tg(_success_msg(len(data.articles), data.stories, send_out["detail"]))
        await ctx.yield_output(
            AgentResponseUpdate(
                contents=[
                    Content(
                        "text",
                        text=_success_msg(
                            len(data.articles), data.stories, send_out["detail"]
                        ),
                    )
                ],
                role="assistant",
                author_name=self.id,
            )
        )


# ── Build workflow | 构建工作流 ──────────────────────────────────────

_config_loader = ConfigLoader(id="0-config-loader")
_feed_fetcher = FeedFetcher(id="1-feed-fetcher")
_article_enricher = ArticleEnricher(id="2-article-enricher")
_story_curator = StoryCurator(id="3-story-curator")
_html_composer = HtmlComposer(id="4-html-composer")
_email_sender = EmailSender(id="5-email-sender")


def _peek_languages() -> list[str]:
    """Eagerly resolve ``config.compose_languages`` at build time so the
    graph shape (linear vs. fan-out) is known before any message flows.
    在构建时预先解析 ``config.compose_languages``，使图的形状（线性 vs. 扇出）
    在任何消息流动之前就已确定。

    Any failure (missing config file in unit tests, parse error, etc.)
    falls back to ``[]`` — the legacy linear shape — so importing this
    module never raises."""
    try:
        result = _step0_config()
        cfg = result["config"]
        return list(getattr(cfg, "compose_languages", []) or [])
    except Exception:  # noqa: BLE001 — defensive: never break import.
        return []


def build_workflow(
    checkpoint_storage: InMemoryCheckpointStorage | None = None,
    languages: list[str] | None = None,
):
    """Build (or rebuild) the workflow. A fresh instance is needed for each checkpoint resume.
    构建（或重建）工作流。每次 checkpoint 恢复都需要一个新实例。

    ``languages`` (when not ``None``) overrides ``config.compose_languages``
    for graph-shape selection — used by ``--languages`` CLI flag so users
    can request a fan-out topology without editing config.yaml. ``None``
    falls back to ``_peek_languages()`` (which reads config at build time)."""
    if languages is None:
        languages = _peek_languages()

    builder = WorkflowBuilder(
        name="ai-weekly-digest",
        start_executor=_config_loader,
        checkpoint_storage=checkpoint_storage,
    )
    builder = (
        builder.add_edge(_config_loader, _feed_fetcher)
        .add_edge(_feed_fetcher, _article_enricher)
        .add_edge(_article_enricher, _story_curator)
        .add_edge(_story_curator, _html_composer)
    )

    if not languages:
        return builder.add_edge(_html_composer, _email_sender).build()

    translators = [TranslateLocale(locale) for locale in languages]
    assembler = LocaleAssembler()
    builder = builder.add_fan_out_edges(_html_composer, translators)
    builder = builder.add_fan_in_edges(translators, assembler)
    builder = builder.add_edge(assembler, _email_sender)
    return builder.build()


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
        print(
            "\n(SVG export needs `apt install graphviz` — copy the Mermaid text above to https://mermaid.live)"
        )
