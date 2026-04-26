"""
FeedFetcher — fetches RSS feeds, extracts articles, and deduplicates.
FeedFetcher — 抓取RSS源、提取文章并去重。

This is Stage 1 of the newsletter pipeline.
这是新闻简报流水线的第1阶段。

Responsibilities:
职责：
- Parallel feed fetching via ThreadPoolExecutor | 通过线程池并行抓取源
- Date-based article filtering (window_days)    | 基于日期的文章过滤（时间窗口）
- GitHub release filtering (semver only)        | GitHub发布过滤（仅保留semver）
- RSS image extraction (media, thumbnail, img)  | RSS图片提取（media、缩略图、img标签）
- Article deduplication by link + title          | 按链接+标题去重
- Caching: reuses fetched-{date}.json if exists  | 缓存：若已存在则复用 fetched-{date}.json
"""

from __future__ import annotations

import concurrent.futures as futures
import datetime as dt
import logging
import re
from typing import Any, Optional

import requests

from core.models import AppConfig, Article, FeedSource, FetchResult
from core.constants import (
    SEMVER_PATTERN,
    _BUILD_NUMBER_PATTERN,
    _HEX_HASH_PATTERN,
    _PRERELEASE_PATTERN,
)
from core.utils import (
    deduplicate_articles,
    feedparser_module,
    fetched_path,
    is_bad_image_url,
    load_articles,
    log_event,
    parse_entry_datetime,
    request_with_retry,
    save_articles,
    strip_html,
    truncate_text,
    url_looks_like_image,
    utc_now,
)


class FeedFetcher:
    """Fetches RSS/Atom feeds in parallel, filters, and deduplicates articles.
    并行抓取RSS/Atom源，过滤并去重文章。
    """

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger

    # ── public API ───────────────────────────────────────────────────────────
    def fetch_all(self, feeds: list[FeedSource], date_label: str) -> FetchResult:
        print("--- Step: Fetching RSS feeds ---")
        path = fetched_path(date_label)
        if path.exists():
            articles = load_articles(path)
            log_event(
                self.logger,
                logging.INFO,
                "fetch_reused",
                path=str(path),
                article_count=len(articles),
            )
            print("    Reusing cached fetch: %d articles from %s" % (len(articles), path.name))
            return FetchResult(
                articles=articles, failed_feeds=[], total_feeds=len(feeds), reused=True
            )

        cutoff = utc_now() - dt.timedelta(days=self.config.fetch_window_days)
        articles: list[Article] = []
        failed_feeds: list[str] = []
        print("    Fetching %d feeds (window=%d days, workers=%d) ..."
              % (len(feeds), self.config.fetch_window_days, self.config.fetch_max_workers))

        with futures.ThreadPoolExecutor(max_workers=self.config.fetch_max_workers) as executor:
            future_map = {
                executor.submit(self._fetch_single, source, cutoff): source
                for source in feeds
            }
            for future in futures.as_completed(future_map):
                fetched_articles, failed_feed = future.result()
                articles.extend(fetched_articles)
                if failed_feed:
                    failed_feeds.append(failed_feed)

        deduped = deduplicate_articles(articles)
        save_articles(path, deduped)
        image_count = sum(1 for a in deduped if a.image_url)
        log_event(
            self.logger,
            logging.INFO,
            "fetch_complete",
            total_feeds=len(feeds),
            failed_feeds=failed_feeds,
            fetched_count=len(articles),
            deduplicated_count=len(deduped),
            image_count=image_count,
            output=str(path),
        )
        print("    Fetched %d articles -> %d after dedup (%d with images, %d feeds failed)"
              % (len(articles), len(deduped), image_count, len(failed_feeds)))
        return FetchResult(
            articles=deduped,
            failed_feeds=failed_feeds,
            total_feeds=len(feeds),
            reused=False,
        )

    # ── internal helpers | 内部工具方法 ─────────────────────────────────────
    def _fetch_single(
        self, source: FeedSource, cutoff: dt.datetime
    ) -> tuple[list[Article], Optional[str]]:
        """Fetch a single feed, parse entries, filter by date, extract images.
        抓取单个源、解析条目、按日期过滤、提取图片。
        Returns (articles, failed_feed_name_or_None).
        返回 (文章列表, 失败的源名称或None)。
        """
        session = requests.Session()
        headers = {"User-Agent": "AI-Weekly-Digest/5.0"}
        try:
            response = request_with_retry(
                session=session,
                method="GET",
                url=source.url,
                timeout=20,
                headers=headers,
                logger=self.logger,
                retries=2,
                delay=2.0,
            )
            parsed = feedparser_module().parse(response.content)
            entries = list(parsed.entries or [])
            entry_limit = source.max_items or self.config.fetch_max_per_feed
            entries = entries[:entry_limit]
            is_gh_releases = self._is_github_releases_feed(source.url)

            articles: list[Article] = []
            for entry in entries:
                title = strip_html(str(entry.get("title", ""))).strip()
                link = str(entry.get("link", "")).strip()
                if not title or not link:
                    continue
                if is_gh_releases and not self._is_meaningful_release(title):
                    continue
                published = parse_entry_datetime(entry)
                if published is not None and published < cutoff:
                    continue
                summary = strip_html(
                    str(entry.get("summary", "") or entry.get("description", ""))
                )
                rss_image = self._extract_rss_image(entry)
                articles.append(
                    Article(
                        title=title,
                        link=link,
                        source_name=source.name,
                        category=source.category,
                        published_date=(
                            published.isoformat() if published is not None else None
                        ),
                        raw_summary=truncate_text(summary, 1200),
                        image_url=rss_image,
                    )
                )
            if is_gh_releases:
                articles = self._pick_latest_github_release(articles)
            log_event(
                self.logger,
                logging.INFO,
                "feed_fetch_success",
                feed=source.name,
                category=source.category,
                count=len(articles),
                images=sum(1 for a in articles if a.image_url),
            )
            return articles, None
        except Exception as exc:
            log_event(
                self.logger,
                logging.ERROR,
                "feed_fetch_failed",
                feed=source.name,
                category=source.category,
                error=str(exc),
            )
            return [], source.name
        finally:
            session.close()

    @staticmethod
    def _is_github_releases_feed(url: str) -> bool:
        """Check if a feed URL is a GitHub releases feed. | 检查是否为GitHub releases源。"""
        return "github.com" in url and "/releases" in url

    @staticmethod
    def _is_meaningful_release(title: str) -> bool:
        """Filter out noise releases: build numbers (b8873), bare hashes.
        过滤无意义的发布：构建号(b8873)、裸哈希。
        """
        first_word = title.strip().split()[0] if title.strip() else ""
        if not first_word:
            return False
        if _BUILD_NUMBER_PATTERN.match(first_word):
            return False
        if _HEX_HASH_PATTERN.match(first_word):
            return False
        return True

    @staticmethod
    def _release_tag_from_link(link: str) -> str:
        """Extract release tag from GitHub release URL.
        从GitHub发布URL中提取版本标签。
        """
        if "/releases/tag/" in link:
            return link.rsplit("/releases/tag/", 1)[-1].split("?")[0].split("#")[0]
        return ""

    def _pick_latest_github_release(self, articles: list[Article]) -> list[Article]:
        """From a list of GitHub release entries, keep only the latest meaningful one.
        从GitHub发布条目列表中只保留最新的有意义版本。
        Prefers stable over pre-release. | 优先选择稳定版而非预发布版。
        """
        if not articles:
            return []
        semver_entries: list[Article] = []
        prerelease_entries: list[Article] = []
        other_entries: list[Article] = []
        for art in articles:
            tag = self._release_tag_from_link(art.link) or art.title.strip().split()[0]
            if SEMVER_PATTERN.match(tag):
                if _PRERELEASE_PATTERN.search(tag):
                    prerelease_entries.append(art)
                else:
                    semver_entries.append(art)
            else:
                other_entries.append(art)

        pool = semver_entries or prerelease_entries or other_entries
        pool.sort(key=lambda a: a.published_date or "", reverse=True)
        return pool[:1]

    @staticmethod
    def _extract_rss_image(entry: Any) -> Optional[str]:
        """Extract the best image URL from an RSS entry.
        从RSS条目中提取最佳图片URL。
        Checks: media_content → media_thumbnail → enclosures → <img> in HTML.
        检查顺序：media_content → media_thumbnail → enclosures → HTML中的<img>。
        """
        # media_content
        media_content = getattr(entry, "media_content", None) or entry.get(
            "media_content", []
        )
        if isinstance(media_content, list):
            for mc in media_content:
                if not isinstance(mc, dict):
                    continue
                mc_url = mc.get("url", "")
                mc_type = str(mc.get("type", ""))
                if mc_url and (mc_type.startswith("image") or url_looks_like_image(mc_url)):
                    if not is_bad_image_url(mc_url):
                        return mc_url

        # media_thumbnail
        media_thumb = getattr(entry, "media_thumbnail", None) or entry.get(
            "media_thumbnail", []
        )
        if isinstance(media_thumb, list) and media_thumb:
            first = media_thumb[0]
            if isinstance(first, dict):
                thumb_url = first.get("url", "")
                if thumb_url and not is_bad_image_url(thumb_url):
                    return thumb_url

        # enclosures
        enclosures = getattr(entry, "enclosures", None) or entry.get("enclosures", [])
        if isinstance(enclosures, list):
            for enc in enclosures:
                if not isinstance(enc, dict):
                    continue
                enc_href = enc.get("href", "") or enc.get("url", "")
                enc_type = str(enc.get("type", ""))
                if enc_href and (
                    enc_type.startswith("image") or url_looks_like_image(enc_href)
                ):
                    if not is_bad_image_url(enc_href):
                        return enc_href

        # First <img> in summary/content HTML
        content_html = str(
            entry.get("summary", "")
            or entry.get("description", "")
            or entry.get("content", [{}])[0].get("value", "")
            if isinstance(entry.get("content"), list) and entry.get("content")
            else entry.get("summary", "")
        )
        img_matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', content_html, re.I)
        for img_url in img_matches:
            if not is_bad_image_url(img_url) and img_url.startswith("http"):
                return img_url

        return None
