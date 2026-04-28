"""
HtmlComposer — renders the newsletter HTML from a template and curated data.
HtmlComposer — 从模板和筛选数据渲染新闻简报HTML。

Follows the same pattern as NewsTemplate/AINewsTemplate.py:
沿用 NewsTemplate/AINewsTemplate.py 的相同模式：
  structured data in → complete HTML string out.
  结构化数据输入 → 完整HTML字符串输出。
The difference is that this uses the v7.html template file instead of an inline template.
与AINewsTemplate的区别在于使用v7.html模板文件而非内联模板。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from core.models import AppConfig, Article
from core.paths import DATA_DIR, OUTPUT_DIR, TEMPLATES_DIR, TMP_HTML_FILE, template_path
from core.constants import TAG_PLACEHOLDER_COLORS
from core.utils import (
    escape_html,
    fetched_path,
    is_bad_image_url,
    load_articles,
    log_event,
    output_html_path,
    truncate_text,
)


_AZ_BADGE_COLORS = {
    "GA": "059669",
    "PREVIEW": "D97706",
    "UPDATE": "0078D4",
    "NEW": "DC2626",
    "AZURE": "0078D4",
}


class HtmlComposer:
    """Composes the newsletter HTML by filling the v7 template with curated story data.
    通过将筛选故事数据填充到v7模板中来组合新闻简报HTML。

    Similar to ``AINewsTemplate.create_newsletter_html`` but reads from ``templates/v7.html``
    and populates card / sidebar / quick-read placeholders.
    类似于 ``AINewsTemplate.create_newsletter_html``，但从 ``templates/v7.html`` 读取
    并填充卡片/侧边栏/快速阅读占位符。
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    # ── public API | 公开接口 ───────────────────────────────────────────
    def compose(
        self,
        stories: list[dict[str, Any]],
        scanned_articles: list[Article],
        date_range: str,
        meta: Optional[dict[str, Any]] = None,
    ) -> str:
        """Take curated stories + all scanned articles and return filled HTML.
        接收筛选故事+所有扫描文章，返回填充完成的HTML。
        Populates C1–C8 cards, Q1–Q5 quick reads, S1–S10 sidebar. | 填充C1-C8卡片、Q1-Q5快速阅读、S1-S10侧边栏。
        """
        print("--- Step: Composing newsletter HTML ---")
        version = getattr(self.config, "template_version", None) or "v7"
        tmpl = template_path(version) if version else (TEMPLATES_DIR / "v7.html")
        template = tmpl.read_text(encoding="utf-8")

        if version == "v8":
            return self._compose_v8(template, stories, scanned_articles, date_range, meta or {})
        return self._compose_v7(template, stories, scanned_articles, date_range)

    def _compose_v7(
        self,
        template: str,
        stories: list[dict[str, Any]],
        scanned_articles: list[Article],
        date_range: str,
    ) -> str:

        source_count = len({article.source_name for article in scanned_articles})
        scanned_count = len(scanned_articles)
        selected_count = len(stories)

        result = template.replace("{{TOTAL_ARTICLES}}", str(scanned_count))
        result = result.replace("{{TOTAL_SOURCES}}", str(source_count))
        result = result.replace("{{TOTAL_SELECTED}}", str(selected_count))

        # ── Featured cards (C1–C8) ──────────────────────────────────────────
        for i in range(8):
            prefix = "C%d" % (i + 1)
            if i < len(stories):
                story = stories[i]
                result = self._replace_card(result, prefix, story)
            else:
                result = self._replace_card_empty(result, prefix)

        # ── Quick reads (Q1–Q5) ─────────────────────────────────────────────
        for i in range(5):
            prefix = "Q%d" % (i + 1)
            idx = 8 + i
            if idx < len(stories):
                story = stories[idx]
                result = self._replace_quick(result, prefix, story)
            else:
                result = self._replace_quick_empty(result, prefix)

        # ── Sidebar items (S1–S10) ──────────────────────────────────────────
        sidebar_items = self._extract_azure_sidebar(scanned_articles)
        for i in range(10):
            prefix = "S%d" % (i + 1)
            if i < len(sidebar_items):
                item = sidebar_items[i]
                result = result.replace("{{%s_TITLE}}" % prefix, escape_html(item["title"]))
                result = result.replace("{{%s_LINK}}" % prefix, escape_html(item["link"]))
                result = result.replace("{{%s_DATE}}" % prefix, escape_html(item["date"]))
            else:
                result = result.replace("{{%s_TITLE}}" % prefix, "")
                result = result.replace("{{%s_LINK}}" % prefix, "#")
                result = result.replace("{{%s_DATE}}" % prefix, "")

        # Remove empty image tags
        result = re.sub(r'<img[^>]+src=""[^>]*/?\s*>', "", result)

        print("    HTML composed: %d stories, %d sources, %d articles scanned"
              % (selected_count, source_count, scanned_count))
        return result

    # ── v8 renderer | v8 渲染 ────────────────────────────────────────────
    def _compose_v8(
        self,
        template: str,
        stories: list[dict[str, Any]],
        scanned_articles: list[Article],
        date_range: str,
        meta: dict[str, Any],
    ) -> str:
        """Render the v8 'Bloomberg-style' newsletter template.
        渲染 v8 “Bloomberg 风” 模板。

        Layout: top bar (issue + date), hero zone (TL;DR + headline + hero image),
        6 featured cards in 2 rows, quick reads, Azure sidebar, footer.
        Missing fields fall back to safe defaults to avoid unresolved placeholders.
        布局：顶部 issue/日期、hero 区（TL;DR + 头条 + 头图）、6 张精选卡㄀2 行、
        快读、Azure 侧边栏、页脚。缺失字段使用安全默认值避免未解析占位符。
        """
        source_count = len({article.source_name for article in scanned_articles})
        scanned_count = len(scanned_articles)
        selected_count = len(stories)

        result = template

        # Top bar | 顶栏
        issue_number = getattr(self.config, "issue_number", 1)
        result = result.replace("{{ISSUE_NUMBER}}", escape_html(str(issue_number)))
        result = result.replace("{{ISSUE_DATE}}", escape_html(date_range))

        # Hero zone | hero 区
        hero_idx_raw = meta.get("hero_image_index", 0)
        try:
            hero_idx = int(hero_idx_raw)
        except (TypeError, ValueError):
            hero_idx = 0
        if hero_idx < 0 or hero_idx >= len(stories):
            hero_idx = 0
        hero_story = stories[hero_idx] if stories else {}

        headline_text = meta.get("headline") or hero_story.get("title") or "AI Weekly Digest"
        tldr_text = meta.get("tldr") or hero_story.get("oneliner") or hero_story.get("summary") or ""

        result = result.replace("{{HERO_TITLE}}", escape_html(str(headline_text)))
        result = result.replace("{{TLDR}}", escape_html(str(tldr_text)))
        result = result.replace("{{ARTICLE_COUNT}}", str(scanned_count))
        result = result.replace("{{SOURCE_COUNT}}", str(source_count))
        result = result.replace("{{STORY_COUNT}}", str(selected_count))
        result = result.replace("{{HERO_LINK}}", escape_html(hero_story.get("link") or "#"))
        result = result.replace(
            "{{HERO_IMAGE}}",
            escape_html(self._get_image_or_placeholder(hero_story) if hero_story else ""),
        )
        result = result.replace("{{HERO_IMG_TITLE}}", escape_html(truncate_text(hero_story.get("title", ""), 80)))
        result = result.replace("{{HERO_IMG_SOURCE}}", escape_html(hero_story.get("source", "")))
        result = result.replace(
            "{{HERO_IMG_DATE}}",
            escape_html(self._format_sidebar_date(hero_story.get("published_date")) or date_range),
        )

        # 6 featured cards C1..C6 | 精选卡片
        # Skip the hero story when filling cards so the hero image isn't duplicated.
        # 跳过作为 hero 的那条，避免与顶部重复。
        card_pool = [s for i, s in enumerate(stories) if i != hero_idx]
        for i in range(6):
            prefix = "C%d" % (i + 1)
            if i < len(card_pool):
                story = card_pool[i]
                tag_upper = (story.get("tag") or "QUICK").upper()
                tag_color = "#" + TAG_PLACEHOLDER_COLORS.get(tag_upper, "6B7280")
                result = result.replace("{{%s_LINK}}" % prefix, escape_html(story.get("link", "#")))
                result = result.replace(
                    "{{%s_IMAGE}}" % prefix, escape_html(self._get_image_or_placeholder(story))
                )
                result = result.replace("{{%s_TAG}}" % prefix, escape_html(tag_upper))
                result = result.replace("{{%s_TAG_COLOR}}" % prefix, tag_color)
                result = result.replace("{{%s_TITLE}}" % prefix, escape_html(story.get("title", "")))
                result = result.replace(
                    "{{%s_DATE}}" % prefix,
                    escape_html(self._format_sidebar_date(story.get("published_date")) or date_range),
                )
                result = result.replace(
                    "{{%s_TIME}}" % prefix, str(story.get("read_time_minutes", 3))
                )
            else:
                result = result.replace("{{%s_LINK}}" % prefix, "#")
                result = result.replace("{{%s_IMAGE}}" % prefix, "")
                result = result.replace("{{%s_TAG}}" % prefix, "")
                result = result.replace("{{%s_TAG_COLOR}}" % prefix, "#6B7280")
                result = result.replace("{{%s_TITLE}}" % prefix, "")
                result = result.replace("{{%s_DATE}}" % prefix, "")
                result = result.replace("{{%s_TIME}}" % prefix, "")

        # Quick reads QR1..QR3 from remaining stories | 快读
        quick_pool = card_pool[6:]
        for i in range(3):
            prefix = "QR%d" % (i + 1)
            if i < len(quick_pool):
                story = quick_pool[i]
                result = result.replace("{{%s_LINK}}" % prefix, escape_html(story.get("link", "#")))
                result = result.replace("{{%s_TITLE}}" % prefix, escape_html(story.get("title", "")))
                result = result.replace(
                    "{{%s_DATE}}" % prefix,
                    escape_html(self._format_sidebar_date(story.get("published_date")) or ""),
                )
            else:
                result = result.replace("{{%s_LINK}}" % prefix, "#")
                result = result.replace("{{%s_TITLE}}" % prefix, "")
                result = result.replace("{{%s_DATE}}" % prefix, "")

        # Azure sidebar AZ1..AZ6 | Azure 侧边栏
        sidebar_items = self._extract_azure_sidebar(scanned_articles, max_items=6)
        for i in range(6):
            prefix = "AZ%d" % (i + 1)
            if i < len(sidebar_items):
                item = sidebar_items[i]
                badge = (item.get("badge") or "AZURE").upper()
                badge_color = "#" + _AZ_BADGE_COLORS.get(badge, "0078D4")
                result = result.replace("{{%s_BADGE}}" % prefix, escape_html(badge))
                result = result.replace("{{%s_BADGE_COLOR}}" % prefix, badge_color)
                result = result.replace("{{%s_LINK}}" % prefix, escape_html(item["link"]))
                result = result.replace("{{%s_TITLE}}" % prefix, escape_html(item["title"]))
                result = result.replace("{{%s_DATE}}" % prefix, escape_html(item["date"]))
            else:
                result = result.replace("{{%s_BADGE}}" % prefix, "")
                result = result.replace("{{%s_BADGE_COLOR}}" % prefix, "#0078D4")
                result = result.replace("{{%s_LINK}}" % prefix, "#")
                result = result.replace("{{%s_TITLE}}" % prefix, "")
                result = result.replace("{{%s_DATE}}" % prefix, "")

        # Strip empty img tags to avoid broken image icons | 清理空 img
        result = re.sub(r'<img[^>]+src=""[^>]*/?\s*>', "", result)

        print(
            "    HTML composed (v8): %d stories, %d sources, %d articles scanned"
            % (selected_count, source_count, scanned_count)
        )
        return result

    def write_outputs(self, date_label: str, html_body: str, logger: logging.Logger) -> None:
        """Write HTML to output dir and tmp mirror.
        将HTML写入输出目录和临时镜像文件。
        """
        print("--- Step: Writing HTML outputs ---")
        out_path = output_html_path(date_label)
        out_path.write_text(html_body, encoding="utf-8")
        TMP_HTML_FILE.write_text(html_body, encoding="utf-8")
        log_event(
            logger,
            logging.INFO,
            "compose_complete",
            output=str(out_path),
            mirror=str(TMP_HTML_FILE),
        )
        print("    Saved: %s" % out_path)
        print("    Mirror: %s" % TMP_HTML_FILE)

    def compose_only(self, logger: logging.Logger) -> int:
        """Re-compose HTML from the latest curated artifact (no fetch/enrich/curate).
        从最新的筛选产物重新组合HTML（不执行拓取/充实/筛选）。
        Used with --compose-only CLI flag. | 配合 --compose-only 命令行参数使用。
        """
        print("--- Step: Compose-only from latest artifact ---")
        curated_file = self._load_latest_artifact("curated")
        date_label = self._path_date_label(curated_file)
        curated, meta = self._load_curated_stories_with_meta(curated_file)
        articles: list[Article] = []
        matching_fetched = fetched_path(date_label)
        if matching_fetched.exists():
            articles = load_articles(matching_fetched)

        from core.utils import week_range_label

        html_body = self.compose(
            curated,
            articles,
            week_range_label(window_days=self.config.fetch_window_days),
            meta=meta,
        )
        self.write_outputs(date_label, html_body, logger)
        log_event(
            logger, logging.INFO, "compose_only_complete", curated_file=str(curated_file)
        )
        return 0

    # ── internal helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _replace_card(result: str, prefix: str, story: dict[str, Any]) -> str:
        result = result.replace(
            "{{%s_TITLE}}" % prefix, escape_html(story.get("title", ""))
        )
        result = result.replace(
            "{{%s_LINK}}" % prefix, escape_html(story.get("link", ""))
        )
        result = result.replace(
            "{{%s_IMAGE}}" % prefix,
            escape_html(HtmlComposer._get_image_or_placeholder(story)),
        )
        result = result.replace(
            "{{%s_ONELINER}}" % prefix, escape_html(story.get("oneliner", ""))
        )
        result = result.replace(
            "{{%s_SOURCE}}" % prefix, escape_html(story.get("source", ""))
        )
        result = result.replace(
            "{{%s_TIME}}" % prefix, str(story.get("read_time_minutes", 3))
        )
        return result

    @staticmethod
    def _replace_card_empty(result: str, prefix: str) -> str:
        """Clear a featured-card placeholder block when no story fills the slot.
        当没有故事填充该位置时，清空精选卡片占位符块。
        """
        result = result.replace("{{%s_TITLE}}" % prefix, "")
        result = result.replace("{{%s_LINK}}" % prefix, "#")
        result = result.replace("{{%s_IMAGE}}" % prefix, "")
        result = result.replace("{{%s_ONELINER}}" % prefix, "")
        result = result.replace("{{%s_SOURCE}}" % prefix, "")
        result = result.replace("{{%s_TIME}}" % prefix, "")
        return result

    @staticmethod
    def _replace_quick(result: str, prefix: str, story: dict[str, Any]) -> str:
        """Fill a quick-read placeholder block (Q1–Q5) in the template.
        在模板中填充快速阅读占位符块(Q1-Q5)。
        """
        result = result.replace(
            "{{%s_TITLE}}" % prefix, escape_html(story.get("title", ""))
        )
        result = result.replace(
            "{{%s_LINK}}" % prefix, escape_html(story.get("link", ""))
        )
        result = result.replace(
            "{{%s_ONELINER}}" % prefix, escape_html(story.get("oneliner", ""))
        )
        result = result.replace(
            "{{%s_SOURCE}}" % prefix, escape_html(story.get("source", ""))
        )
        return result

    @staticmethod
    def _replace_quick_empty(result: str, prefix: str) -> str:
        """Clear a quick-read placeholder block when no story fills the slot.
        当没有故事填充该位置时，清空快速阅读占位符块。
        """
        result = result.replace("{{%s_TITLE}}" % prefix, "")
        result = result.replace("{{%s_LINK}}" % prefix, "#")
        result = result.replace("{{%s_ONELINER}}" % prefix, "")
        result = result.replace("{{%s_SOURCE}}" % prefix, "")
        return result

    @staticmethod
    def _get_image_or_placeholder(story: dict[str, Any]) -> str:
        """Return the story image URL, or generate a placeholder image via placehold.co.
        返回故事图片URL，或通过placehold.co生成占位图片。
        """
        url = story.get("image_url", "")
        if url and url not in ("None", "null") and not is_bad_image_url(url):
            return url
        tag = story.get("tag", "NEWS")
        source = story.get("source", "AI")
        color = TAG_PLACEHOLDER_COLORS.get(tag, "6B7280")
        text = "%s%%0A%s" % (tag, source.replace(" ", "+"))
        return (
            "https://placehold.co/190x107/%s/ffffff?text=%s&font=source-sans-pro"
            % (color, text)
        )

    @staticmethod
    def _format_sidebar_date(published_date: Optional[str]) -> str:
        """Format an ISO date string to 'Mon DD, YYYY' for the sidebar display.
        将ISO日期字符串格式化为'Mon DD, YYYY'用于侧边栏显示。
        """
        if not published_date:
            return ""
        try:
            parsed = dt.datetime.fromisoformat(
                published_date.replace("Z", "+00:00")
            ).astimezone(dt.timezone.utc)
            return parsed.strftime("%b %d, %Y")
        except Exception:
            return ""

    def _extract_azure_sidebar(
        self, scanned_articles: list[Article], max_items: int = 10
    ) -> list[dict[str, str]]:
        """Extract Azure/Microsoft articles for the sidebar section (S1–S10).
        提取Azure/Microsoft文章用于侧边栏部分(S1-S10)。
        """
        azure_articles = [
            a
            for a in scanned_articles
            if a.category.lower() in ("azure_microsoft", "azure_cloud")
            or "azure" in a.source_name.lower()
            or "microsoft" in a.source_name.lower()
        ]
        azure_articles.sort(key=lambda a: a.published_date or "", reverse=True)
        items: list[dict[str, str]] = []
        seen_links: set[str] = set()
        for article in azure_articles:
            if article.link in seen_links:
                continue
            seen_links.add(article.link)
            items.append(
                {
                    "title": truncate_text(article.title, 80),
                    "link": article.link,
                    "date": self._format_sidebar_date(article.published_date),
                }
            )
            if len(items) >= max_items:
                break
        return items

    @staticmethod
    def _load_latest_artifact(prefix: str) -> Path:
        """Find the most recent JSON artifact by prefix in the data directory.
        在数据目录中按前缀查找最新的JSON产物文件。
        """
        pattern = "%s-*.json" % prefix
        matches = sorted(DATA_DIR.glob(pattern))
        if not matches:
            raise FileNotFoundError("No %s artifacts found in %s" % (prefix, DATA_DIR))
        return matches[-1]

    @staticmethod
    def _path_date_label(path: Path) -> str:
        """Extract YYYY-MM-DD date label from a file path name.
        从文件路径名中提取YYYY-MM-DD日期标签。
        """
        match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
        if not match:
            raise ValueError("Could not infer date from %s" % path.name)
        return match.group(1)

    def _load_curated_stories(self, path: Path) -> list[dict[str, Any]]:
        """Load and normalize curated stories from a JSON file.
        从 JSON 文件加载并规范化筛选故事。
        """
        stories, _ = self._load_curated_stories_with_meta(path)
        return stories

    def _load_curated_stories_with_meta(
        self, path: Path
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Load curated artifact, returning normalized stories and v8 meta if any.
        加载筛选产物，返回规范化的故事与 v8 meta（如有）。
        """
        from core.content_curator import ContentCurator

        raw = json.loads(path.read_text(encoding="utf-8"))
        meta: dict[str, Any] = {}
        if isinstance(raw, dict):
            stories_raw = raw.get("stories", [])
            raw_meta = raw.get("meta")
            if isinstance(raw_meta, dict):
                meta = raw_meta
        elif isinstance(raw, list):
            stories_raw = raw
        else:
            raise ValueError("Expected curated file to contain a JSON array or object")
        curator = ContentCurator(self.config, logging.getLogger("ai-newsletter-v5"))
        return curator._normalize_output(stories_raw), meta
