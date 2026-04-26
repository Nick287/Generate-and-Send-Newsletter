"""
ContentCurator — uses LLM to select and score the best stories for the newsletter.
ContentCurator — 使用LLM筛选并评分新闻简报的最佳故事。

This is Stage 3 of the newsletter pipeline.
这是新闻简报流水线的第3阶段。

Responsibilities:
职责：
- Send articles to LLM for curation into scored story objects  | 将文章发送给LLM筛选为评分故事对象
- Sanitize and normalize LLM output                           | 清理并规范化LLM输出
- Provide heuristic fallback when LLM fails                   | LLM失败时提供启发式降级方案
- Inject RSS/OG images into curated stories                   | 将RSS/OG图片注入筛选后的故事
- Save curated-{date}.json artifact                           | 保存 curated-{date}.json 产物
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from core.models import AppConfig, Article
from core.paths import CURATE_PROMPT_FILE
from core.constants import VALID_TAGS
from core.llm_client import LlmClient
from core.utils import (
    curated_path,
    is_bad_image_url,
    log_event,
    tg,
    truncate_text,
)


# re-use curated_path from utils (it's a path helper)
# but curate_prompt_text is curate-specific
def _curate_prompt_text() -> str:
    content = CURATE_PROMPT_FILE.read_text(encoding="utf-8").strip()
    if not content:
        raise RuntimeError("curate prompt file is empty")
    return content


class ContentCurator:
    """Selects and ranks the top stories using LLM curation + fallback heuristics.
    使用LLM筛选+启发式降级方案来选择和排名最佳故事。
    """

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.llm = LlmClient(config, logger)

    # ── public API | 公开接口 ───────────────────────────────────────────
    def curate(
        self, articles: list[Article], date_label: str
    ) -> tuple[list[dict[str, Any]], bool]:
        """Send articles to LLM for curation; fallback to heuristic ranking.
        将文章发送给LLM进行筛选；失败时降级为启发式排名。
        Returns (curated_stories, critical_failure_flag). | 返回 (筛选故事, 严重失败标志)。
        """
        print("--- Step: Curating stories with LLM ---")
        prompt_text = _curate_prompt_text()
        payload = []
        for article in articles:
            payload.append(
                {
                    "title": article.title,
                    "link": article.link,
                    "source": article.source_name,
                    "category": article.category,
                    "published_date": article.published_date,
                    "raw_summary": truncate_text(article.raw_summary, 600),
                    "full_text_excerpt": truncate_text(
                        article.full_text_excerpt or article.raw_summary,
                        self.config.enrich_max_body_chars,
                    ),
                    "image_url": article.image_url or article.og_image,
                    "pre_score": article.pre_score,
                }
            )

        user_prompt = (
            "Curate these articles into the required flat JSON array of story objects. "
            "Use the exact schema from the system prompt. Do not wrap in markdown.\n\n"
            "Articles:\n%s" % json.dumps(payload, ensure_ascii=False)
        )

        critical_failure = False
        try:
            content = self.llm.chat(prompt_text, user_prompt, retries=2, delay_seconds=5.0)
            curated = self._normalize_output(LlmClient.parse_json_array(content))
            log_event(self.logger, logging.INFO, "curate_llm_success", story_count=len(curated))
            print("    LLM curated %d stories" % len(curated))
        except Exception as exc:
            critical_failure = True
            log_event(self.logger, logging.ERROR, "curate_llm_failed", error=str(exc))
            curated = self._fallback_output(articles)
            tg("⚠️ AI Weekly Digest curate stage fallback used: %s" % str(exc)[:300])
            print("    LLM curation failed, using fallback (%d stories)" % len(curated))

        curated = self._inject_images(curated, articles)
        path = curated_path(date_label)
        path.write_text(json.dumps(curated, ensure_ascii=False, indent=2), encoding="utf-8")
        image_count = sum(1 for s in curated if s.get("image_url"))
        log_event(
            self.logger,
            logging.INFO,
            "curate_complete",
            output=str(path),
            story_count=len(curated),
            image_count=image_count,
            critical_failure=critical_failure,
        )
        print("    Curated %d stories (%d with images)" % (len(curated), image_count))
        return curated, critical_failure

    # ── internal helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _sanitize_story(story: dict[str, Any]) -> Optional[dict[str, Any]]:
        title = str(story.get("title", "")).strip()
        link = str(story.get("link", "")).strip()
        source = str(story.get("source", "")).strip()
        summary = str(story.get("summary", "")).strip()
        oneliner = str(story.get("oneliner", "")).strip()
        tag = str(story.get("tag", "QUICK")).strip().upper()
        if not title or not link:
            return None
        if tag not in VALID_TAGS:
            tag = "QUICK"
        try:
            score = int(round(float(story.get("score", 0))))
        except Exception:
            score = 0
        try:
            read_time = int(round(float(story.get("read_time_minutes", 1))))
        except Exception:
            read_time = 1
        image_url = str(story.get("image_url", "")).strip() or None
        if image_url and is_bad_image_url(image_url):
            image_url = None
        return {
            "title": title,
            "link": link,
            "source": source,
            "summary": summary,
            "oneliner": oneliner or truncate_text(summary, 120),
            "score": max(0, min(25, score)),
            "read_time_minutes": max(1, read_time),
            "image_url": image_url,
            "tag": tag,
        }

    def _normalize_output(self, raw_stories: Any) -> list[dict[str, Any]]:
        """Validate, sanitize, deduplicate, and sort LLM-curated stories.
        验证、清理、去重并排序LLM筛选的故事。
        """
        if not isinstance(raw_stories, list):
            raise ValueError("Curated output must be a JSON array")
        stories: list[dict[str, Any]] = []
        seen_links: set[str] = set()
        for item in raw_stories:
            if not isinstance(item, dict):
                continue
            sanitized = self._sanitize_story(item)
            if sanitized is None:
                continue
            if sanitized["link"] in seen_links:
                continue
            seen_links.add(sanitized["link"])
            stories.append(sanitized)
        stories.sort(key=lambda s: -s.get("score", 0))
        return stories

    def _fallback_output(self, articles: list[Article]) -> list[dict[str, Any]]:
        """Generate curated output from raw articles when LLM curation fails.
        LLM筛选失败时，从原始文章生成筛选输出。
        Uses pre-scores to rank, takes top 13. | 使用预评分排名，取前13篇。
        """
        from core.article_enricher import ArticleEnricher

        sorted_articles = sorted(
            articles,
            key=lambda a: -(a.pre_score or ArticleEnricher._heuristic_pre_score(a)),
        )
        stories: list[dict[str, Any]] = []
        seen_links: set[str] = set()
        for article in sorted_articles[:13]:
            if article.link in seen_links:
                continue
            seen_links.add(article.link)
            stories.append(
                {
                    "title": article.title,
                    "link": article.link,
                    "source": article.source_name,
                    "summary": article.raw_summary,
                    "oneliner": truncate_text(article.raw_summary, 120),
                    "score": int(
                        round(
                            (
                                article.pre_score
                                or ArticleEnricher._heuristic_pre_score(article)
                            )
                            * 2.5
                        )
                    ),
                    "read_time_minutes": self._infer_read_time(article),
                    "image_url": article.image_url,
                    "tag": self._infer_tag(article),
                }
            )
        stories.sort(key=lambda s: -s.get("score", 0))
        return stories

    @staticmethod
    def _infer_read_time(article: Article) -> int:
        """Estimate reading time in minutes from article text length.
        根据文章文本长度估算阅读时间(分钟)。
        """
        text = article.full_text_excerpt or article.raw_summary or article.title
        words = re.findall(r"\w+", text)
        return max(1, int(round(max(len(words), 1) / 220.0)))

    @staticmethod
    def _infer_tag(article: Article) -> str:
        """Infer story tag (AZURE/RESEARCH/TOOL/HEADLINE/QUICK) from category and text.
        根据分类和文本推断故事标签(AZURE/RESEARCH/TOOL/HEADLINE/QUICK)。
        """
        cat = article.category.lower()
        text = (article.title + " " + article.raw_summary).lower()
        if cat in {"azure_microsoft", "competitor_cloud"} or "azure" in text:
            return "AZURE"
        if cat == "research" or "paper" in text or "arxiv" in text:
            return "RESEARCH"
        if cat in {"releases", "labs"} or any(
            kw in text for kw in ["release", "launch", "tool", "update"]
        ):
            return "TOOL"
        if article.pre_score and article.pre_score >= 7.0:
            return "HEADLINE"
        return "QUICK"

    @staticmethod
    def _inject_images(
        stories: list[dict[str, Any]], articles: list[Article]
    ) -> list[dict[str, Any]]:
        """Fill in missing image URLs in curated stories from original article data.
        从原始文章数据中填充筛选故事中缺失的图片URL。
        """
        image_map: dict[str, str] = {}
        for article in articles:
            best = article.image_url or article.og_image
            if best and not is_bad_image_url(best):
                image_map[article.link] = best
        for story in stories:
            link = story.get("link", "")
            if link in image_map and not story.get("image_url"):
                story["image_url"] = image_map[link]
        return stories
