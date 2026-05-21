"""Telegram public-channel HTML fetcher (via /s/ preview pages).

This fetcher hits only the public `t.me/s/<channel>` HTML view. It does not
authenticate, does not use Bot API, does not bypass any access control, and
runs at most 1 request per channel per pipeline run, capped at 20 posts.

See core/feeds/LEGAL.md for the Path A posture and operational mitigations.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Iterable, Optional
from urllib.parse import urlparse

import lxml.html
import requests

from core.models import Article, FeedSource
from core.utils.http import request_with_retry
from core.utils.logging import log_event

DEFAULT_AD_KEYWORDS: tuple[str, ...] = (
    "oaibest",
    "api.oaibest",
    "Buy ads:",
    "telega.io",
    "推广",
    "广告",
    "代充",
    "🛒",
)

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_MAX_POSTS = 20
_TITLE_MAX = 100
_BG_IMAGE_RE = re.compile(r"background-image\s*:\s*url\(['\"]?([^'\")]+)['\"]?\)")


def _channel_from_url(url: str) -> str:
    parts = url.rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "s":
        return parts[-1]
    return parts[-1]


def _normalize_url(url: str) -> str:
    if "/t.me/s/" in url:
        return url
    return url.replace("//t.me/", "//t.me/s/", 1)


def _first_sentence(text: str, limit: int = _TITLE_MAX) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    for sep in ("。", ".", "！", "!", "？", "?", "\n"):
        idx = text.find(sep)
        if 0 < idx <= limit:
            return text[: idx + 1].strip()
    return text[:limit].strip()


def _contains_ad(body: str, ad_keywords: Iterable[str]) -> bool:
    lower = body.lower()
    for kw in ad_keywords:
        if not kw:
            continue
        if kw.lower() in lower:
            return True
    return False


def _http_url_or_none(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        return url
    return None


def parse_html(
    html: str,
    source: FeedSource,
    *,
    channel: str,
    ad_keywords: Iterable[str],
) -> list[Article]:
    """Pure parse: HTML string -> list[Article]. No network. No I/O."""
    if not html:
        return []

    root = lxml.html.fromstring(html)
    wrappers = root.cssselect("div.tgme_widget_message_wrap")
    ad_kw = tuple(ad_keywords) or DEFAULT_AD_KEYWORDS
    cap = min(source.max_items or _MAX_POSTS, _MAX_POSTS)
    articles: list[Article] = []

    for wrap in wrappers:
        if len(articles) >= cap:
            break

        if wrap.cssselect(".tgme_widget_message_service"):
            continue
        if wrap.cssselect(".tgme_widget_message_pinned"):
            continue

        msg_nodes = wrap.cssselect(".tgme_widget_message[data-post]")
        if not msg_nodes:
            continue
        msg = msg_nodes[0]
        data_post = msg.get("data-post") or ""
        if "/" not in data_post:
            continue
        if msg.get("data-view") == "pinned":
            continue
        post_id = data_post.split("/", 1)[1]
        link = f"https://t.me/{channel}/{post_id}"

        time_nodes = wrap.cssselect("time[datetime]")
        published_date = time_nodes[0].get("datetime") if time_nodes else ""

        body_nodes = wrap.cssselect(".tgme_widget_message_text")
        body = " ".join(n.text_content().strip() for n in body_nodes).strip()

        if _contains_ad(body, ad_kw):
            continue

        image_url: Optional[str] = None
        photo_nodes = wrap.cssselect("a.tgme_widget_message_photo_wrap")
        for p in photo_nodes:
            style = p.get("style") or ""
            m = _BG_IMAGE_RE.search(style)
            if m:
                image_url = _http_url_or_none(m.group(1))
                if image_url:
                    break
        if not image_url:
            preview_nodes = wrap.cssselect("a.tgme_widget_message_link_preview")
            for pv in preview_nodes:
                img_nodes = pv.cssselect(".link_preview_image")
                for img in img_nodes:
                    style = img.get("style") or ""
                    m = _BG_IMAGE_RE.search(style)
                    if m:
                        image_url = _http_url_or_none(m.group(1))
                        if image_url:
                            break
                if image_url:
                    break

        title = (
            _first_sentence(body) or f"[{channel}] {published_date[:10] or ''}".strip()
        )

        articles.append(
            Article(
                title=title,
                link=link,
                source_name=source.name,
                category=source.category,
                published_date=published_date or "",
                raw_summary=body,
                full_text_excerpt=body,
                image_url=image_url,
                og_image=image_url,
                pre_score=None,
                skip_enrich=True,
            )
        )

    return articles


def fetch(
    source: FeedSource,
    cutoff: dt.datetime,
    config,
    logger: logging.Logger,
) -> tuple[list[Article], Optional[str]]:
    """Fetch + parse a single Telegram public channel.

    Returns (articles, failed_source_name_or_None). NEVER raises.
    """
    url = _normalize_url(source.url)
    channel = _channel_from_url(url)

    try:
        session = requests.Session()
        session.headers["User-Agent"] = _BROWSER_UA
        resp = request_with_retry(
            session, "GET", url, timeout=20, logger=logger, retries=2, delay=2.0
        )

        ad_keywords: tuple[str, ...] = DEFAULT_AD_KEYWORDS
        user_kw = getattr(config, "ad_keywords", None) if config is not None else None
        if user_kw:
            merged = list(DEFAULT_AD_KEYWORDS)
            for kw in user_kw:
                if kw and kw not in merged:
                    merged.append(kw)
            ad_keywords = tuple(merged)

        articles = parse_html(
            resp.text, source, channel=channel, ad_keywords=ad_keywords
        )

        log_event(
            logger,
            logging.INFO,
            "feed_fetch_success",
            feed=source.name,
            category=source.category,
            count=len(articles),
            images=sum(1 for a in articles if a.image_url),
        )
        return (articles, None)

    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "feed_fetch_failed",
            feed=source.name,
            category=source.category,
            error=str(exc),
        )
        return ([], source.name)
