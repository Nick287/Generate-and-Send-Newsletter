"""
ArticleEnricher — pre-scores articles and enriches top candidates with full text.
ArticleEnricher — 对文章进行预评分，并为高分候选文章提取全文。

This is Stage 2 of the newsletter pipeline.
这是新闻简报流水线的第2阶段。

Responsibilities:
职责：
- LLM-based pre-scoring (1-10) with heuristic fallback | 基于LLM的预评分(1-10)，带启发式降级
- Full-text extraction via trafilatura + readability   | 通过trafilatura+readability提取全文
- OpenGraph image extraction from article pages        | 从文章页面提取OpenGraph图片
- Saves enriched-{date}.json artifact                  | 保存 enriched-{date}.json 产物
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict
from typing import Any, Optional

import requests
from lxml import html as lxml_html

from core.models import AppConfig, Article
from core.llm_client import LlmClient
from core.utils import (
    article_sort_key,
    enriched_path,
    is_bad_image_url,
    log_event,
    readability_document_class,
    request_with_retry,
    save_articles,
    strip_html,
    trafilatura_module,
    truncate_text,
)


class ArticleEnricher:
    """Pre-scores articles with LLM / heuristics, then fetches full text for top candidates.
    用LLM/启发式方法对文章预评分，然后为高分候选获取全文。
    """

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.llm = LlmClient(config, logger)

    # ── public API ───────────────────────────────────────────────────────────
    def enrich(self, articles: list[Article], date_label: str) -> list[Article]:
        print("--- Step: Pre-scoring & enriching articles ---")
        pre_scored = self._pre_score(articles)
        candidates = pre_scored[: self.config.enrich_top_candidates]
        print("    Top %d candidates selected for enrichment" % len(candidates))

        enriched: list[Article] = []
        session = requests.Session()
        try:
            for index, article in enumerate(candidates):
                if index > 0 and self.config.enrich_fetch_delay > 0:
                    time.sleep(self.config.enrich_fetch_delay)
                enriched.append(self._enrich_article(article, session))
        finally:
            session.close()

        path = enriched_path(date_label)
        save_articles(path, enriched)
        image_count = sum(1 for a in enriched if a.image_url)
        log_event(
            self.logger,
            logging.INFO,
            "enrich_complete",
            candidate_count=len(candidates),
            image_count=image_count,
            output=str(path),
        )
        print("    Enriched %d articles (%d with images)" % (len(enriched), image_count))
        return enriched

    # ── pre-scoring ──────────────────────────────────────────────────────────
    def _pre_score(self, articles: list[Article]) -> list[Article]:
        if not articles:
            return []
        print("    Pre-scoring %d articles ..." % len(articles))

        batch = []
        for index, article in enumerate(articles):
            batch.append(
                {
                    "index": index,
                    "title": article.title,
                    "summary": truncate_text(article.raw_summary, 280),
                    "source": article.source_name,
                    "category": article.category,
                    "published_date": article.published_date,
                }
            )

        system_prompt = "You score newsletter candidates from 1-10. Return only JSON."
        user_prompt = (
            "Score each article from 1 to 10 for newsletter priority. Favor Azure relevance, customer value,"
            " technical actionability, novelty, and source quality. Return a JSON array of objects with"
            " keys index and score only.\n\nArticles:\n%s"
            % json.dumps(batch, ensure_ascii=False)
        )

        scores: dict[int, float] = {}
        try:
            content = self.llm.chat(system_prompt, user_prompt, retries=1, delay_seconds=3.0)
            parsed = LlmClient.parse_json_array(content)
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                try:
                    raw_index = item.get("index")
                    raw_score = item.get("score")
                    if raw_index is None or raw_score is None:
                        continue
                    index = int(raw_index)
                    score = float(raw_score)
                except Exception:
                    continue
                scores[index] = max(1.0, min(10.0, score))
            log_event(
                self.logger, logging.INFO, "pre_score_llm_success", scored_count=len(scores)
            )
            print("    LLM pre-scored %d articles" % len(scores))
        except Exception as exc:
            log_event(self.logger, logging.WARNING, "pre_score_llm_fallback", error=str(exc))
            print("    LLM pre-score failed, using heuristic fallback")

        scored_articles: list[Article] = []
        for index, article in enumerate(articles):
            cloned = Article(**asdict(article))
            cloned.pre_score = scores.get(index, self._heuristic_pre_score(article))
            scored_articles.append(cloned)
        return sorted(scored_articles, key=article_sort_key)

    @staticmethod
    def _heuristic_pre_score(article: Article) -> float:
        """Keyword-based heuristic score (fallback when LLM is unavailable).
        基于关键词的启发式评分（LLM不可用时的降级方案）。
        Boosts Azure/Microsoft/OpenAI keywords. | 提升Azure/Microsoft/OpenAI等关键词的分数。
        """
        text = (article.title + " " + article.raw_summary).lower()
        score = 4.0
        keyword_weights = {
            "azure": 2.5, "microsoft": 2.0, "openai": 1.5, "anthropic": 1.2,
            "google": 1.0, "aws": 0.8, "gcp": 0.8, "ga": 1.0, "launch": 1.0,
            "release": 0.6, "benchmark": 0.8, "paper": 0.8, "research": 0.8,
            "copilot": 1.0, "foundry": 1.5,
        }
        for keyword, weight in keyword_weights.items():
            if keyword in text:
                score += weight
        if article.published_date is None:
            score -= 1.0
        if article.category in {"azure_microsoft", "labs", "research"}:
            score += 0.5
        return max(1.0, min(10.0, round(score, 1)))

    # ── single article enrichment | 单篇文章充实 ──────────────────────────
    def _enrich_article(self, article: Article, session: requests.Session) -> Article:
        """Fetch article page, extract full text and OG image.
        抓取文章页面，提取全文和OG图片。
        Falls back to RSS summary on failure. | 失败时回退到RSS摘要。
        """
        enriched = Article(**asdict(article))
        fallback = truncate_text(article.raw_summary, self.config.enrich_max_body_chars)
        try:
            response = request_with_retry(
                session=session,
                method="GET",
                url=article.link,
                timeout=self.config.enrich_fetch_timeout,
                logger=self.logger,
                retries=1,
                delay=2.0,
                headers={"User-Agent": "AI-Weekly-Digest/5.0"},
            )
            body = self._extract_with_trafilatura(response.text, self.config.enrich_max_body_chars)
            if not body:
                body = self._extract_with_readability(response.text, self.config.enrich_max_body_chars)
            if not body:
                body = fallback
            enriched.full_text_excerpt = body or fallback
            og_image = self._extract_og_image(response.text)
            if og_image:
                enriched.og_image = og_image
                enriched.image_url = og_image
            log_event(
                self.logger,
                logging.INFO,
                "article_enriched",
                title=article.title,
                source=article.source_name,
                body_chars=len(enriched.full_text_excerpt),
                has_image=bool(enriched.image_url),
            )
            return enriched
        except Exception as exc:
            enriched.full_text_excerpt = fallback
            log_event(
                self.logger,
                logging.WARNING,
                "article_enrich_fallback",
                title=article.title,
                source=article.source_name,
                error=str(exc),
            )
            return enriched

    @staticmethod
    def _extract_with_trafilatura(html_text: str, limit: int) -> str:
        """Extract clean text from HTML using trafilatura.
        使用trafilatura从HTML中提取干净文本。
        """
        try:
            extracted = trafilatura_module().extract(
                html_text,
                include_comments=False,
                include_links=False,
                include_images=False,
                favor_precision=True,
            )
            if extracted:
                return truncate_text(strip_html(extracted), limit)
        except Exception:
            return ""
        return ""

    @staticmethod
    def _extract_with_readability(html_text: str, limit: int) -> str:
        """Extract clean text from HTML using readability (fallback parser).
        使用readability从HTML中提取干净文本（备用解析器）。
        """
        try:
            summary_html = readability_document_class()(html_text).summary()
            text = lxml_html.fromstring(summary_html).text_content()
            return truncate_text(strip_html(text), limit)
        except Exception:
            return ""

    @staticmethod
    def _extract_og_image(html_text: str) -> Optional[str]:
        """Extract OpenGraph or Twitter Card image URL from HTML meta tags.
        从HTML meta标签中提取OpenGraph或Twitter Card图片URL。
        """
        og_match = re.search(
            r'<meta\s+(?:property|name)=["\'](?:og:image|twitter:image)["\']'
            r'\s+content=["\'](https?://[^"\']+)["\']',
            html_text,
            re.I,
        )
        if not og_match:
            og_match = re.search(
                r'<meta\s+content=["\'](https?://[^"\']+)["\']'
                r'\s+(?:property|name)=["\'](?:og:image|twitter:image)["\']',
                html_text,
                re.I,
            )
        if og_match:
            url = og_match.group(1)
            if not is_bad_image_url(url):
                return url
        return None
