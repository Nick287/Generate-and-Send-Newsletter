#!/usr/bin/env python3
# pyright: reportMissingImports=false
"""AI Weekly Digest newsletter pipeline v5."""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import datetime as dt
import email.utils
import html
import importlib
import json
import logging
import os
import re
import string
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import requests
import yaml
from lxml import html as lxml_html

ROOT = Path(__file__).resolve().parent
PROMPTS_DIR = ROOT / "prompts"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
FEEDS_FILE = ROOT / "feeds.yaml"
CONFIG_FILE = ROOT / "config.yaml"
TEMPLATES_DIR = ROOT / "templates"
CURATE_PROMPT_FILE = PROMPTS_DIR / "curate-v5.md"
TMP_HTML_FILE = Path(os.environ.get("NEWSLETTER_TMP_HTML", "/tmp/ai-newsletter.html"))
ACS_SECRET_FILE = Path(os.environ.get("ACS_SECRET_FILE", "")) if os.environ.get("ACS_SECRET_FILE") else None
DEFAULT_LLM_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_LLM_MODEL = "gpt-4o"
DEFAULT_ACS_SENDER = ""

BAD_IMAGE_PATTERNS = [
    "arxiv.org/icons",
    "static.arxiv.org",
    "gravatar.com",
    "wp-content/uploads/avatar",
    "s.w.org",
    "feeds.feedburner.com",
    "pixel",
    "track",
    "1x1",
    "spacer",
    "icon",
    # GitHub auto-generated OG images (just screenshots of release/repo UI)
    "opengraph.githubassets.com",
    "repository-images.githubusercontent.com",
    "avatars.githubusercontent.com",
]

# Match semver-ish release tags: v1.2.3, 0.19.1, v0.21.1-rc1
SEMVER_PATTERN = re.compile(r"^v?\d+\.\d+(\.\d+)?(-[\w.]+)?$")
_BUILD_NUMBER_PATTERN = re.compile(r"^b\d+$")
_HEX_HASH_PATTERN = re.compile(r"^[a-f0-9]{7,}$")
_PRERELEASE_PATTERN = re.compile(r"(rc\d*|alpha|beta|preview|nightly|dev)", re.IGNORECASE)


def is_github_releases_feed(url: str) -> bool:
    return "github.com" in url and "/releases" in url


def is_meaningful_release(title: str) -> bool:
    """Filter out build-number releases like b8873, b8875 and bare hashes."""
    first_word = title.strip().split()[0] if title.strip() else ""
    if not first_word:
        return False
    if _BUILD_NUMBER_PATTERN.match(first_word):
        return False
    if _HEX_HASH_PATTERN.match(first_word):
        return False
    return True


def _release_tag_from_link(link: str) -> str:
    # https://github.com/owner/repo/releases/tag/v1.2.3 -> v1.2.3
    if "/releases/tag/" in link:
        return link.rsplit("/releases/tag/", 1)[-1].split("?")[0].split("#")[0]
    return ""


def pick_latest_github_release(articles: list["Article"]) -> list["Article"]:
    """From a list of GitHub release entries (single repo), keep only the latest
    meaningful semver release. Prefer non-prerelease; fall back to prerelease only
    if nothing else exists."""
    if not articles:
        return []
    semver_entries = []
    prerelease_entries = []
    other_entries = []
    for art in articles:
        tag = _release_tag_from_link(art.link) or art.title.strip().split()[0]
        if SEMVER_PATTERN.match(tag):
            if _PRERELEASE_PATTERN.search(tag):
                prerelease_entries.append(art)
            else:
                semver_entries.append(art)
        else:
            other_entries.append(art)

    def _sort_key(a: "Article"):
        return a.published_date or ""

    pool = semver_entries or prerelease_entries or other_entries
    pool.sort(key=_sort_key, reverse=True)
    return pool[:1]

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

VALID_TAGS = {"HEADLINE", "RESEARCH", "TOOL", "AZURE", "QUICK"}


@dataclass
class FeedSource:
    category: str
    name: str
    url: str
    max_items: Optional[int] = None
    skip_enrich: bool = False


@dataclass
class AppConfig:
    issue_number: int
    recipients: list[str]
    acs_sender: str
    acs_connection_string: str
    email_provider: str
    sendgrid_api_key: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    smtp_use_ssl: bool
    llm_endpoint: str
    llm_api_key: str
    llm_model: str
    llm_temperature: float
    llm_max_tokens: int
    llm_timeout: int
    fetch_window_days: int
    fetch_max_workers: int
    fetch_max_per_feed: int
    arxiv_cap_per_category: int
    fetch_fail_threshold: float
    enrich_top_candidates: int
    enrich_fetch_delay: float
    enrich_fetch_timeout: int
    enrich_max_body_chars: int
    cleanup_retention_days: int


@dataclass
class Article:
    title: str
    link: str
    source_name: str
    category: str
    published_date: Optional[str]
    raw_summary: str
    full_text_excerpt: str = ""
    og_image: Optional[str] = None
    image_url: Optional[str] = None
    pre_score: Optional[float] = None


@dataclass
class FetchResult:
    articles: list[Article]
    failed_feeds: list[str]
    total_feeds: int
    reused: bool


@dataclass
class StageOutcome:
    critical_failure: bool = False
    partial_failure: bool = False
    message: str = ""


def load_module(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Required dependency '%s' is not installed in the active Python environment"
            % module_name
        ) from exc


def feedparser_module() -> Any:
    return load_module("feedparser")


def trafilatura_module() -> Any:
    return load_module("trafilatura")


def readability_document_class() -> Any:
    return load_module("readability").Document


def email_client_class() -> Any:
    return load_module("azure.communication.email").EmailClient


def tg(msg: str) -> None:
    """Optional progress notifier. Set TG_NOTIFY_SCRIPT env var to a script that takes one arg."""
    script_path = os.environ.get("TG_NOTIFY_SCRIPT", "")
    if not script_path:
        return
    script = Path(script_path)
    if not script.exists():
        return
    try:
        subprocess.run([str(script), msg], timeout=15, capture_output=True)
    except Exception:
        pass


def setup_logging(date_label: str) -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ai-newsletter-v5")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(message)s")
    file_handler = logging.FileHandler(
        DATA_DIR / ("run-%s.log" % date_label), encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    payload = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "level": logging.getLevelName(level),
        "event": event,
    }
    payload.update(fields)
    logger.log(level, json.dumps(payload, ensure_ascii=False, sort_keys=True))


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def today_label(now: Optional[dt.datetime] = None) -> str:
    current = now or utc_now()
    return current.date().isoformat()


def week_range_label(now: Optional[dt.datetime] = None, window_days: int = 7) -> str:
    current = now or utc_now()
    start = (current - dt.timedelta(days=max(window_days - 1, 0))).date()
    end = current.date()
    if start.year == end.year:
        return "%s – %s" % (start.strftime("%b %d"), end.strftime("%b %d, %Y"))
    return "%s – %s" % (start.strftime("%b %d, %Y"), end.strftime("%b %d, %Y"))


def fetched_path(date_label: str) -> Path:
    return DATA_DIR / ("fetched-%s.json" % date_label)


def enriched_path(date_label: str) -> Path:
    return DATA_DIR / ("enriched-%s.json" % date_label)


def curated_path(date_label: str) -> Path:
    return DATA_DIR / ("curated-%s.json" % date_label)


def output_html_path(date_label: str) -> Path:
    return OUTPUT_DIR / ("newsletter-%s.html" % date_label)


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_HTML_FILE.parent.mkdir(parents=True, exist_ok=True)


def cleanup_old_data_files(retention_days: int, logger: logging.Logger) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = utc_now() - dt.timedelta(days=retention_days)
    deleted: list[str] = []
    for path in DATA_DIR.iterdir():
        if not path.is_file():
            continue
        try:
            modified = dt.datetime.fromtimestamp(
                path.stat().st_mtime, tz=dt.timezone.utc
            )
            if modified < cutoff:
                path.unlink()
                deleted.append(path.name)
        except Exception as exc:
            log_event(
                logger, logging.WARNING, "cleanup_error", file=path.name, error=str(exc)
            )
    log_event(
        logger,
        logging.INFO,
        "cleanup_complete",
        deleted_files=deleted,
        retention_days=retention_days,
    )


def load_yaml_file(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("Failed to read %s: %s" % (path, exc)) from exc


def validate_feeds(doc: Any) -> list[FeedSource]:
    if not isinstance(doc, dict) or not doc:
        raise ValueError("feeds.yaml must be a non-empty mapping of category -> feeds")

    sources: list[FeedSource] = []
    for category, feeds in doc.items():
        if not isinstance(category, str) or not category.strip():
            raise ValueError("feeds.yaml categories must be non-empty strings")
        if not isinstance(feeds, list):
            raise ValueError("feeds.yaml category %s must contain a list" % category)
        for index, feed in enumerate(feeds):
            if not isinstance(feed, dict):
                raise ValueError(
                    "feeds.yaml entry %s[%s] must be an object" % (category, index)
                )
            name = feed.get("name")
            url = feed.get("url")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    "feeds.yaml entry %s[%s] is missing a valid name"
                    % (category, index)
                )
            if not isinstance(url, str) or not url.strip():
                raise ValueError(
                    "feeds.yaml entry %s[%s] is missing a valid url" % (category, index)
                )
            max_items = feed.get("max_items")
            if max_items is not None:
                max_items = int(max_items)
            skip_enrich = bool(feed.get("skip_enrich", False))
            sources.append(
                FeedSource(
                    category=category,
                    name=name.strip(),
                    url=url.strip(),
                    max_items=max_items,
                    skip_enrich=skip_enrich,
                )
            )
    return sources


def validate_config(doc: Any) -> AppConfig:
    if not isinstance(doc, dict):
        raise ValueError("config.yaml must be a mapping")

    issue_number = doc.get("issue_number", 1)
    # Support new nested 'email:' block (preferred) or legacy flat keys
    email_cfg = doc.get("email", {}) if isinstance(doc.get("email"), dict) else {}
    recipients = email_cfg.get("recipients", doc.get("recipients"))
    acs_sender = email_cfg.get("acs_sender", doc.get("acs_sender", DEFAULT_ACS_SENDER))
    acs_connection_string = email_cfg.get("acs_connection_string", "") or ""
    email_provider = (email_cfg.get("provider") or "acs").lower().strip()
    sendgrid_api_key = email_cfg.get("sendgrid_api_key", "") or ""
    smtp_host = email_cfg.get("smtp_host", "") or ""
    smtp_port = int(email_cfg.get("smtp_port", 587) or 587)
    smtp_user = email_cfg.get("smtp_user", "") or ""
    smtp_pass = email_cfg.get("smtp_pass", "") or ""
    smtp_use_ssl = bool(email_cfg.get("smtp_use_ssl", False))

    llm = doc.get("llm", {})
    fetch = doc.get("fetch", {})
    enrich = doc.get("enrich", {})
    cleanup = doc.get("cleanup", {})

    if not isinstance(issue_number, int) or issue_number < 1:
        raise ValueError("config.yaml issue_number must be a positive integer")
    if (
        not isinstance(recipients, list)
        or not recipients
        or not all(isinstance(item, str) and item.strip() for item in recipients)
    ):
        raise ValueError("config recipients must be a non-empty list of strings (under email.recipients or top-level)")
    if not isinstance(acs_sender, str):
        acs_sender = ""
    if email_provider == "acs" and not acs_sender.strip():
        raise ValueError("config.yaml email.acs_sender required when provider=acs")
    if not isinstance(llm, dict):
        raise ValueError("config.yaml llm must be a mapping")
    if not isinstance(fetch, dict):
        raise ValueError("config.yaml fetch must be a mapping")
    if not isinstance(enrich, dict):
        raise ValueError("config.yaml enrich must be a mapping")
    if not isinstance(cleanup, dict):
        raise ValueError("config.yaml cleanup must be a mapping")

    endpoint = llm.get("endpoint", DEFAULT_LLM_ENDPOINT)
    api_key = llm.get("api_key", "") or os.environ.get("LLM_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    model = llm.get("model", DEFAULT_LLM_MODEL)
    temperature = llm.get("temperature", 0.2)
    max_tokens = llm.get("max_tokens", 8000)
    timeout = llm.get("timeout", 180)
    fetch_window_days = fetch.get("window_days", 7)
    fetch_max_workers = fetch.get("max_workers", 10)
    fetch_max_per_feed = fetch.get("max_per_feed", 25)
    arxiv_cap = fetch.get("arxiv_cap_per_category", 10)
    fail_threshold = fetch.get("fail_threshold", 0.5)
    top_candidates = enrich.get("top_candidates", 40)
    fetch_delay = enrich.get("fetch_delay", 0.5)
    fetch_timeout = enrich.get("fetch_timeout", 15)
    max_body_chars = enrich.get("max_body_chars", 3000)
    retention_days = cleanup.get("retention_days", 30)

    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("config.yaml llm.endpoint must be a non-empty string")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("config.yaml llm.model must be a non-empty string")
    if not isinstance(temperature, (float, int)):
        raise ValueError("config.yaml llm.temperature must be a number")
    if not isinstance(max_tokens, int) or max_tokens < 256:
        raise ValueError("config.yaml llm.max_tokens must be an integer >= 256")
    if not isinstance(timeout, int) or timeout < 10:
        raise ValueError("config.yaml llm.timeout must be an integer >= 10")
    if not isinstance(fetch_window_days, int) or fetch_window_days < 1:
        raise ValueError("config.yaml fetch.window_days must be >= 1")
    if not isinstance(fetch_max_workers, int) or fetch_max_workers < 1:
        raise ValueError("config.yaml fetch.max_workers must be >= 1")
    if not isinstance(fetch_max_per_feed, int) or fetch_max_per_feed < 1:
        raise ValueError("config.yaml fetch.max_per_feed must be >= 1")
    if not isinstance(arxiv_cap, int) or arxiv_cap < 1:
        raise ValueError("config.yaml fetch.arxiv_cap_per_category must be >= 1")
    if (
        not isinstance(fail_threshold, (float, int))
        or float(fail_threshold) <= 0
        or float(fail_threshold) > 1
    ):
        raise ValueError("config.yaml fetch.fail_threshold must be between 0 and 1")
    if not isinstance(top_candidates, int) or top_candidates < 1:
        raise ValueError("config.yaml enrich.top_candidates must be >= 1")
    if not isinstance(fetch_delay, (float, int)) or float(fetch_delay) < 0:
        raise ValueError("config.yaml enrich.fetch_delay must be >= 0")
    if not isinstance(fetch_timeout, int) or fetch_timeout < 1:
        raise ValueError("config.yaml enrich.fetch_timeout must be >= 1")
    if not isinstance(max_body_chars, int) or max_body_chars < 200:
        raise ValueError("config.yaml enrich.max_body_chars must be >= 200")
    if not isinstance(retention_days, int) or retention_days < 1:
        raise ValueError("config.yaml cleanup.retention_days must be >= 1")

    return AppConfig(
        issue_number=issue_number,
        recipients=[item.strip() for item in recipients],
        acs_sender=acs_sender.strip(),
        acs_connection_string=acs_connection_string.strip(),
        email_provider=email_provider,
        sendgrid_api_key=sendgrid_api_key.strip(),
        smtp_host=smtp_host.strip(),
        smtp_port=smtp_port,
        smtp_user=smtp_user.strip(),
        smtp_pass=smtp_pass,
        smtp_use_ssl=smtp_use_ssl,
        llm_endpoint=endpoint.strip(),
        llm_api_key=(api_key or "").strip(),
        llm_model=model.strip(),
        llm_temperature=float(temperature),
        llm_max_tokens=max_tokens,
        llm_timeout=timeout,
        fetch_window_days=fetch_window_days,
        fetch_max_workers=fetch_max_workers,
        fetch_max_per_feed=fetch_max_per_feed,
        arxiv_cap_per_category=arxiv_cap,
        fetch_fail_threshold=float(fail_threshold),
        enrich_top_candidates=top_candidates,
        enrich_fetch_delay=float(fetch_delay),
        enrich_fetch_timeout=fetch_timeout,
        enrich_max_body_chars=max_body_chars,
        cleanup_retention_days=retention_days,
    )


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def truncate_text(text: str, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0].strip() + "…"


def parse_entry_datetime(entry: Any) -> Optional[dt.datetime]:
    parsed_fields = ["published_parsed", "updated_parsed", "created_parsed"]
    text_fields = ["published", "updated", "created", "dc_date", "date"]

    for field in parsed_fields:
        value = (
            entry.get(field) if isinstance(entry, dict) else getattr(entry, field, None)
        )
        if value:
            try:
                return dt.datetime(*value[:6], tzinfo=dt.timezone.utc)
            except Exception:
                continue

    for field in text_fields:
        raw = (
            entry.get(field) if isinstance(entry, dict) else getattr(entry, field, None)
        )
        if not raw:
            continue
        try:
            parsed = email.utils.parsedate_to_datetime(str(raw))
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt.timezone.utc)
                return parsed.astimezone(dt.timezone.utc)
        except Exception:
            pass
        try:
            iso = str(raw).replace("Z", "+00:00")
            parsed = dt.datetime.fromisoformat(iso)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except Exception:
            continue
    return None


def article_datetime(article: Article) -> Optional[dt.datetime]:
    if not article.published_date:
        return None
    try:
        return dt.datetime.fromisoformat(
            article.published_date.replace("Z", "+00:00")
        ).astimezone(dt.timezone.utc)
    except Exception:
        return None


def article_sort_key(article: Article) -> tuple[int, float, float, int, str]:
    published = article_datetime(article)
    has_date = 0 if published is not None else 1
    timestamp = -published.timestamp() if published is not None else float("inf")
    pre_score = -(article.pre_score if article.pre_score is not None else -1.0)
    summary_length = -len(article.raw_summary or "")
    return (has_date, timestamp, pre_score, summary_length, article.title.lower())


def normalize_title(title: str) -> str:
    lowered = (title or "").lower()
    translator = str.maketrans("", "", string.punctuation)
    normalized = lowered.translate(translator)
    return re.sub(r"\s+", " ", normalized).strip()


def title_tokens(title: str) -> set[str]:
    normalized = normalize_title(title)
    return {token for token in normalized.split(" ") if token}


def title_similarity(a: str, b: str) -> float:
    a_tokens = title_tokens(a)
    b_tokens = title_tokens(b)
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    denominator = max(len(a_tokens), len(b_tokens))
    if denominator == 0:
        return 0.0
    return overlap / float(denominator)


def better_article(candidate: Article, current: Article) -> Article:
    candidate_summary_len = len(candidate.raw_summary or "")
    current_summary_len = len(current.raw_summary or "")
    if candidate_summary_len > current_summary_len:
        return candidate
    if candidate_summary_len < current_summary_len:
        return current
    candidate_has_date = article_datetime(candidate) is not None
    current_has_date = article_datetime(current) is not None
    if candidate_has_date and not current_has_date:
        return candidate
    if current_has_date and not candidate_has_date:
        return current
    return (
        candidate
        if article_sort_key(candidate) < article_sort_key(current)
        else current
    )


def deduplicate_articles(articles: list[Article]) -> list[Article]:
    by_link: dict[str, Article] = {}
    for article in articles:
        existing = by_link.get(article.link)
        if existing is None:
            by_link[article.link] = article
        else:
            by_link[article.link] = better_article(article, existing)

    deduped: list[Article] = []
    for article in sorted(by_link.values(), key=article_sort_key):
        matched_index: Optional[int] = None
        for index, kept in enumerate(deduped):
            if title_similarity(article.title, kept.title) > 0.6:
                matched_index = index
                break
        if matched_index is None:
            deduped.append(article)
            continue
        deduped[matched_index] = better_article(article, deduped[matched_index])

    return sorted(deduped, key=article_sort_key)


def save_articles(path: Path, articles: list[Article]) -> None:
    payload = [asdict(article) for article in articles]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_articles(path: Path) -> list[Article]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Expected %s to contain a JSON array" % path)
    articles: list[Article] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        articles.append(
            Article(
                title=str(item.get("title", "")).strip(),
                link=str(item.get("link", "")).strip(),
                source_name=str(item.get("source_name", "")).strip(),
                category=str(item.get("category", "")).strip(),
                published_date=item.get("published_date"),
                raw_summary=str(item.get("raw_summary", "")).strip(),
                full_text_excerpt=str(item.get("full_text_excerpt", "")).strip(),
                og_image=item.get("og_image"),
                image_url=item.get("image_url"),
                pre_score=(
                    float(item["pre_score"])
                    if item.get("pre_score") is not None
                    else None
                ),
            )
        )
    return articles


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    timeout: int,
    logger: logging.Logger,
    retries: int = 2,
    delay: float = 2.0,
    **kwargs: Any,
) -> requests.Response:
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 2):
        try:
            response = session.request(
                method=method, url=url, timeout=timeout, **kwargs
            )
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            log_event(
                logger,
                logging.WARNING,
                "http_retry",
                method=method,
                url=url,
                attempt=attempt,
                error=str(exc),
            )
            if attempt <= retries:
                time.sleep(delay)
    raise RuntimeError(
        "%s %s failed after retries: %s" % (method.upper(), url, last_error)
    )


def is_bad_image_url(url: str) -> bool:
    if not url:
        return True
    lowered = url.lower()
    for pattern in BAD_IMAGE_PATTERNS:
        if pattern in lowered:
            return True
    return False


def url_looks_like_image(url: str) -> bool:
    lowered = url.lower().split("?")[0]
    return any(lowered.endswith(ext) for ext in IMAGE_EXTENSIONS)


def extract_rss_image(entry: Any) -> Optional[str]:
    # 1. media_content
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

    # 2. media_thumbnail
    media_thumb = getattr(entry, "media_thumbnail", None) or entry.get(
        "media_thumbnail", []
    )
    if isinstance(media_thumb, list) and media_thumb:
        first = media_thumb[0]
        if isinstance(first, dict):
            thumb_url = first.get("url", "")
            if thumb_url and not is_bad_image_url(thumb_url):
                return thumb_url

    # 3. enclosures
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

    # 4. First <img> in summary/content HTML
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


def fetch_single_feed(
    source: FeedSource,
    cutoff: dt.datetime,
    config: AppConfig,
    logger: logging.Logger,
) -> tuple[list[Article], Optional[str]]:
    session = requests.Session()
    headers = {"User-Agent": "AI-Weekly-Digest/5.0"}
    try:
        response = request_with_retry(
            session=session,
            method="GET",
            url=source.url,
            timeout=20,
            headers=headers,
            logger=logger,
            retries=2,
            delay=2.0,
        )
        parsed = feedparser_module().parse(response.content)
        entries = list(parsed.entries or [])
        entry_limit = source.max_items or config.fetch_max_per_feed
        entries = entries[:entry_limit]
        is_gh_releases = is_github_releases_feed(source.url)

        articles: list[Article] = []
        for entry in entries:
            title = strip_html(str(entry.get("title", ""))).strip()
            link = str(entry.get("link", "")).strip()
            if not title or not link:
                continue
            if is_gh_releases and not is_meaningful_release(title):
                continue
            published = parse_entry_datetime(entry)
            if published is not None and published < cutoff:
                continue
            summary = strip_html(
                str(entry.get("summary", "") or entry.get("description", ""))
            )
            rss_image = extract_rss_image(entry)
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
            articles = pick_latest_github_release(articles)
        log_event(
            logger,
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
            logger,
            logging.ERROR,
            "feed_fetch_failed",
            feed=source.name,
            category=source.category,
            error=str(exc),
        )
        return [], source.name
    finally:
        session.close()


def stage_fetch(
    config: AppConfig,
    feeds: list[FeedSource],
    date_label: str,
    logger: logging.Logger,
) -> FetchResult:
    path = fetched_path(date_label)
    if path.exists():
        articles = load_articles(path)
        log_event(
            logger,
            logging.INFO,
            "fetch_reused",
            path=str(path),
            article_count=len(articles),
        )
        return FetchResult(
            articles=articles, failed_feeds=[], total_feeds=len(feeds), reused=True
        )

    cutoff = utc_now() - dt.timedelta(days=config.fetch_window_days)
    articles: list[Article] = []
    failed_feeds: list[str] = []
    with futures.ThreadPoolExecutor(max_workers=config.fetch_max_workers) as executor:
        future_map = {
            executor.submit(fetch_single_feed, source, cutoff, config, logger): source
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
        logger,
        logging.INFO,
        "fetch_complete",
        total_feeds=len(feeds),
        failed_feeds=failed_feeds,
        fetched_count=len(articles),
        deduplicated_count=len(deduped),
        image_count=image_count,
        output=str(path),
    )
    return FetchResult(
        articles=deduped,
        failed_feeds=failed_feeds,
        total_feeds=len(feeds),
        reused=False,
    )


def heuristic_pre_score(article: Article) -> float:
    text = (article.title + " " + article.raw_summary).lower()
    score = 4.0
    keyword_weights = {
        "azure": 2.5,
        "microsoft": 2.0,
        "openai": 1.5,
        "anthropic": 1.2,
        "google": 1.0,
        "aws": 0.8,
        "gcp": 0.8,
        "ga": 1.0,
        "launch": 1.0,
        "release": 0.6,
        "benchmark": 0.8,
        "paper": 0.8,
        "research": 0.8,
        "copilot": 1.0,
        "foundry": 1.5,
    }
    for keyword, weight in keyword_weights.items():
        if keyword in text:
            score += weight
    if article.published_date is None:
        score -= 1.0
    if article.category in {"azure_microsoft", "labs", "research"}:
        score += 0.5
    return max(1.0, min(10.0, round(score, 1)))


def parse_json_array(content: str) -> list[Any]:
    value = (content or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", value)
        value = re.sub(r"\n```$", "", value).strip()
    start = value.find("[")
    end = value.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response did not contain a JSON array")
    return json.loads(value[start : end + 1])


def llm_chat(
    config: AppConfig,
    logger: logging.Logger,
    system_prompt: str,
    user_prompt: str,
    retries: int,
    delay_seconds: float,
) -> str:
    payload = {
        "model": config.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": config.llm_temperature,
        "max_completion_tokens": config.llm_max_tokens,
    }
    session = requests.Session()
    headers = {"Content-Type": "application/json"}
    if config.llm_api_key:
        # Send both auth styles so the same code works against:
        #  - OpenAI / OpenAI-compatible endpoints (Bearer token)
        #  - Azure APIM in front of AOAI (subscription key header)
        # Each backend ignores the header it doesn't recognise.
        headers["Authorization"] = "Bearer %s" % config.llm_api_key
        headers["Ocp-Apim-Subscription-Key"] = config.llm_api_key
    try:
        for attempt in range(1, retries + 2):
            try:
                response = request_with_retry(
                    session=session,
                    method="POST",
                    url=config.llm_endpoint,
                    timeout=config.llm_timeout,
                    logger=logger,
                    retries=0,
                    delay=0,
                    json=payload,
                    headers=headers,
                )
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("LLM response content was empty")
                return content
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "llm_call_failed",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt <= retries:
                    time.sleep(delay_seconds)
                else:
                    raise
    finally:
        session.close()
    raise RuntimeError("LLM call exited without a response")


def stage_pre_score(
    articles: list[Article], config: AppConfig, logger: logging.Logger
) -> list[Article]:
    if not articles:
        return []

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
        content = llm_chat(
            config, logger, system_prompt, user_prompt, retries=1, delay_seconds=3.0
        )
        parsed = parse_json_array(content)
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
            logger, logging.INFO, "pre_score_llm_success", scored_count=len(scores)
        )
    except Exception as exc:
        log_event(logger, logging.WARNING, "pre_score_llm_fallback", error=str(exc))

    scored_articles: list[Article] = []
    for index, article in enumerate(articles):
        cloned = Article(**asdict(article))
        cloned.pre_score = scores.get(index, heuristic_pre_score(article))
        scored_articles.append(cloned)
    return sorted(scored_articles, key=article_sort_key)


def extract_with_trafilatura(html_text: str, limit: int) -> str:
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


def extract_with_readability(html_text: str, limit: int) -> str:
    try:
        summary_html = readability_document_class()(html_text).summary()
        text = lxml_html.fromstring(summary_html).text_content()
        return truncate_text(strip_html(text), limit)
    except Exception:
        return ""


def extract_og_image(html_text: str) -> Optional[str]:
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


def enrich_article(
    article: Article,
    session: requests.Session,
    config: AppConfig,
    logger: logging.Logger,
) -> Article:
    enriched = Article(**asdict(article))
    fallback = truncate_text(article.raw_summary, config.enrich_max_body_chars)
    try:
        response = request_with_retry(
            session=session,
            method="GET",
            url=article.link,
            timeout=config.enrich_fetch_timeout,
            logger=logger,
            retries=1,
            delay=2.0,
            headers={"User-Agent": "AI-Weekly-Digest/5.0"},
        )
        body = extract_with_trafilatura(response.text, config.enrich_max_body_chars)
        if not body:
            body = extract_with_readability(response.text, config.enrich_max_body_chars)
        if not body:
            body = fallback
        enriched.full_text_excerpt = body or fallback
        og_image = extract_og_image(response.text)
        if og_image:
            enriched.og_image = og_image
            enriched.image_url = og_image
        log_event(
            logger,
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
            logger,
            logging.WARNING,
            "article_enrich_fallback",
            title=article.title,
            source=article.source_name,
            error=str(exc),
        )
        return enriched


def stage_enrich(
    articles: list[Article], config: AppConfig, date_label: str, logger: logging.Logger
) -> list[Article]:
    pre_scored = stage_pre_score(articles, config, logger)
    candidates = pre_scored[: config.enrich_top_candidates]
    enriched: list[Article] = []
    session = requests.Session()
    try:
        for index, article in enumerate(candidates):
            if index > 0 and config.enrich_fetch_delay > 0:
                time.sleep(config.enrich_fetch_delay)
            enriched.append(enrich_article(article, session, config, logger))
    finally:
        session.close()

    path = enriched_path(date_label)
    save_articles(path, enriched)
    image_count = sum(1 for a in enriched if a.image_url)
    log_event(
        logger,
        logging.INFO,
        "enrich_complete",
        candidate_count=len(candidates),
        image_count=image_count,
        output=str(path),
    )
    return enriched


def curate_prompt_text() -> str:
    content = CURATE_PROMPT_FILE.read_text(encoding="utf-8").strip()
    if not content:
        raise RuntimeError("curate prompt file is empty")
    return content


def infer_read_time_minutes(article: Article) -> int:
    text = article.full_text_excerpt or article.raw_summary or article.title
    words = re.findall(r"\w+", text)
    return max(1, int(round(max(len(words), 1) / 220.0)))


def infer_tag(article: Article) -> str:
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


def sanitize_story(story: dict[str, Any]) -> Optional[dict[str, Any]]:
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


def normalize_curated_output(raw_stories: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_stories, list):
        raise ValueError("Curated output must be a JSON array")

    stories: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    for item in raw_stories:
        if not isinstance(item, dict):
            continue
        sanitized = sanitize_story(item)
        if sanitized is None:
            continue
        if sanitized["link"] in seen_links:
            continue
        seen_links.add(sanitized["link"])
        stories.append(sanitized)

    stories.sort(key=lambda s: -s.get("score", 0))
    return stories


def fallback_curated_output(articles: list[Article]) -> list[dict[str, Any]]:
    sorted_articles = sorted(
        articles, key=lambda a: -(a.pre_score or heuristic_pre_score(a))
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
                    round((article.pre_score or heuristic_pre_score(article)) * 2.5)
                ),
                "read_time_minutes": infer_read_time_minutes(article),
                "image_url": article.image_url,
                "tag": infer_tag(article),
            }
        )
    stories.sort(key=lambda s: -s.get("score", 0))
    return stories


def inject_images(
    stories: list[dict[str, Any]], articles: list[Article]
) -> list[dict[str, Any]]:
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


def stage_curate(
    articles: list[Article],
    config: AppConfig,
    date_label: str,
    logger: logging.Logger,
) -> tuple[list[dict[str, Any]], bool]:
    prompt_text = curate_prompt_text()
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
                    config.enrich_max_body_chars,
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
        content = llm_chat(
            config, logger, prompt_text, user_prompt, retries=2, delay_seconds=5.0
        )
        curated = normalize_curated_output(parse_json_array(content))
        log_event(logger, logging.INFO, "curate_llm_success", story_count=len(curated))
    except Exception as exc:
        critical_failure = True
        log_event(logger, logging.ERROR, "curate_llm_failed", error=str(exc))
        curated = fallback_curated_output(articles)
        tg("⚠️ AI Weekly Digest curate stage fallback used: %s" % str(exc)[:300])

    curated = inject_images(curated, articles)
    path = curated_path(date_label)
    path.write_text(json.dumps(curated, ensure_ascii=False, indent=2), encoding="utf-8")
    image_count = sum(1 for s in curated if s.get("image_url"))
    log_event(
        logger,
        logging.INFO,
        "curate_complete",
        output=str(path),
        story_count=len(curated),
        image_count=image_count,
        critical_failure=critical_failure,
    )
    return curated, critical_failure


TAG_PLACEHOLDER_COLORS = {
    "HEADLINE": "0078D4",
    "RESEARCH": "5E6AD2",
    "TOOL": "059669",
    "AZURE": "0078D4",
    "QUICK": "6B7280",
}


def get_image_or_placeholder(story: dict[str, Any]) -> str:
    url = story.get("image_url", "")
    if url and url not in ("None", "null") and not is_bad_image_url(url):
        return url
    tag = story.get("tag", "NEWS")
    source = story.get("source", "AI")
    color = TAG_PLACEHOLDER_COLORS.get(tag, "6B7280")
    text = "%s%%0A%s" % (tag, source.replace(" ", "+"))
    return "https://placehold.co/190x107/%s/ffffff?text=%s&font=source-sans-pro" % (
        color,
        text,
    )


def escape_html(value: str) -> str:
    return html.escape(value or "", quote=True)


def load_latest_artifact(prefix: str) -> Path:
    pattern = "%s-*.json" % prefix
    matches = sorted(DATA_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError("No %s artifacts found in %s" % (prefix, DATA_DIR))
    return matches[-1]


def path_date_label(path: Path) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if not match:
        raise ValueError("Could not infer date from %s" % path.name)
    return match.group(1)


def load_curated_stories(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Expected curated file to contain a JSON array")
    return normalize_curated_output(raw)


def format_sidebar_date(published_date: Optional[str]) -> str:
    if not published_date:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(
            published_date.replace("Z", "+00:00")
        ).astimezone(dt.timezone.utc)
        return parsed.strftime("%b %d, %Y")
    except Exception:
        return ""


def extract_azure_sidebar_items(
    scanned_articles: list[Article], max_items: int = 10
) -> list[dict[str, str]]:
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
                "date": format_sidebar_date(article.published_date),
            }
        )
        if len(items) >= max_items:
            break
    return items


def compose_html(
    stories: list[dict[str, Any]],
    scanned_articles: list[Article],
    config: AppConfig,
    date_range: str,
) -> str:
    template_path = TEMPLATES_DIR / "v7.html"
    template = template_path.read_text(encoding="utf-8")

    source_count = len({article.source_name for article in scanned_articles})
    scanned_count = len(scanned_articles)
    selected_count = len(stories)

    result = template.replace("{{TOTAL_ARTICLES}}", str(scanned_count))
    result = result.replace("{{TOTAL_SOURCES}}", str(source_count))
    result = result.replace("{{TOTAL_SELECTED}}", str(selected_count))

    for i in range(8):
        prefix = "C%d" % (i + 1)
        if i < len(stories):
            story = stories[i]
            result = result.replace(
                "{{%s_TITLE}}" % prefix, escape_html(story.get("title", ""))
            )
            result = result.replace(
                "{{%s_LINK}}" % prefix, escape_html(story.get("link", ""))
            )
            result = result.replace(
                "{{%s_IMAGE}}" % prefix,
                escape_html(get_image_or_placeholder(story)),
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
        else:
            result = result.replace("{{%s_TITLE}}" % prefix, "")
            result = result.replace("{{%s_LINK}}" % prefix, "#")
            result = result.replace("{{%s_IMAGE}}" % prefix, "")
            result = result.replace("{{%s_ONELINER}}" % prefix, "")
            result = result.replace("{{%s_SOURCE}}" % prefix, "")
            result = result.replace("{{%s_TIME}}" % prefix, "")

    for i in range(5):
        prefix = "Q%d" % (i + 1)
        idx = 8 + i
        if idx < len(stories):
            story = stories[idx]
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
        else:
            result = result.replace("{{%s_TITLE}}" % prefix, "")
            result = result.replace("{{%s_LINK}}" % prefix, "#")
            result = result.replace("{{%s_ONELINER}}" % prefix, "")
            result = result.replace("{{%s_SOURCE}}" % prefix, "")

    sidebar_items = extract_azure_sidebar_items(scanned_articles)
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

    result = re.sub(r'<img[^>]+src=""[^>]*/?\s*>', "", result)

    return result


def write_html_outputs(date_label: str, html_body: str, logger: logging.Logger) -> None:
    output_path = output_html_path(date_label)
    output_path.write_text(html_body, encoding="utf-8")
    TMP_HTML_FILE.write_text(html_body, encoding="utf-8")
    log_event(
        logger,
        logging.INFO,
        "compose_complete",
        output=str(output_path),
        mirror=str(TMP_HTML_FILE),
    )


def read_acs_connection_string(config: "AppConfig" = None) -> Optional[str]:
    value = os.environ.get("ACS_CONNECTION_STRING")
    if value and value.strip():
        return value.strip()
    if config is not None and getattr(config, "acs_connection_string", ""):
        return config.acs_connection_string
    if ACS_SECRET_FILE is not None and ACS_SECRET_FILE.exists():
        try:
            content = ACS_SECRET_FILE.read_text(encoding="utf-8").strip()
            return content or None
        except Exception:
            return None
    return None


def send_via_acs(
    connection_string: str,
    sender: str,
    recipients: list[str],
    subject: str,
    html_body: str,
) -> dict[str, Any]:
    client = email_client_class().from_connection_string(connection_string)
    message = {
        "senderAddress": sender,
        "recipients": {"to": [{"address": item} for item in recipients]},
        "content": {
            "subject": subject,
            "html": html_body,
            "plainText": "AI Weekly Digest HTML email",
        },
    }
    poller = client.begin_send(message)
    result = poller.result()
    if isinstance(result, dict):
        return result
    as_dict = getattr(result, "as_dict", None)
    if callable(as_dict):
        converted = as_dict()
        if isinstance(converted, dict):
            return converted
    return {
        "status": getattr(result, "status", None),
        "id": getattr(result, "id", None),
    }


def append_send_log(entry: dict[str, Any], logger: logging.Logger) -> None:
    path = DATA_DIR / "send-log.json"
    existing: list[Any] = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                existing = raw
        except Exception as exc:
            log_event(logger, logging.WARNING, "send_log_load_failed", error=str(exc))
    existing.append(entry)
    path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def send_via_sendgrid(
    api_key: str,
    sender: str,
    recipients: list[str],
    subject: str,
    html_body: str,
) -> dict[str, Any]:
    payload = {
        "personalizations": [{"to": [{"email": r} for r in recipients]}],
        "from": {"email": sender},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
    }
    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        json=payload,
        headers={
            "Authorization": "Bearer %s" % api_key,
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    if resp.status_code in (200, 202):
        return {"status": "succeeded", "id": resp.headers.get("X-Message-Id")}
    return {"status": "failed", "detail": resp.text[:300]}


def send_via_smtp(
    host: str,
    port: int,
    user: str,
    password: str,
    use_ssl: bool,
    sender: str,
    recipients: list[str],
    subject: str,
    html_body: str,
) -> dict[str, Any]:
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText("AI Weekly Digest HTML email", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_cls(host, port, timeout=60) as smtp:
        if not use_ssl:
            try:
                smtp.starttls()
            except Exception:
                pass
        if user:
            smtp.login(user, password)
        smtp.sendmail(sender, recipients, msg.as_string())
    return {"status": "succeeded", "id": "smtp"}


def stage_send(
    config: AppConfig,
    recipients: list[str],
    subject: str,
    html_body: str,
    date_label: str,
    logger: logging.Logger,
) -> tuple[bool, str]:
    provider = (config.email_provider or "acs").lower()

    def _do_send() -> dict[str, Any]:
        if provider == "sendgrid":
            api_key = os.environ.get("SENDGRID_API_KEY", "") or config.sendgrid_api_key
            if not api_key:
                raise RuntimeError("SENDGRID_API_KEY not set")
            sender = config.acs_sender or os.environ.get("EMAIL_SENDER", "")
            if not sender:
                raise RuntimeError("email sender (acs_sender or EMAIL_SENDER) not set")
            return send_via_sendgrid(api_key, sender, recipients, subject, html_body)
        if provider == "smtp":
            host = config.smtp_host or os.environ.get("SMTP_HOST", "")
            port = config.smtp_port or int(os.environ.get("SMTP_PORT", "587") or 587)
            user = config.smtp_user or os.environ.get("SMTP_USER", "")
            pw = config.smtp_pass or os.environ.get("SMTP_PASS", "")
            sender = config.acs_sender or user
            if not host or not sender:
                raise RuntimeError("SMTP host/sender not configured")
            return send_via_smtp(
                host, port, user, pw, config.smtp_use_ssl,
                sender, recipients, subject, html_body,
            )
        # default ACS
        connection_string = read_acs_connection_string(config)
        if not connection_string:
            raise RuntimeError("ACS connection string not found in env or config")
        return send_via_acs(
            connection_string, config.acs_sender, recipients, subject, html_body
        )

    last_error = ""
    for attempt in range(1, 3):
        try:
            result = _do_send()
            status = str(result.get("status") or "").lower()
            if status in {"succeeded", "success"}:
                detail = "%s send succeeded (%s)" % (provider, result.get("id") or "no-id")
                append_send_log(
                    {
                        "date": date_label,
                        "subject": subject,
                        "recipients": recipients,
                        "status": "success",
                        "detail": detail,
                        "provider": provider,
                        "result": result,
                        "ts": utc_now().isoformat(),
                    },
                    logger,
                )
                log_event(
                    logger, logging.INFO, "send_success",
                    recipients=recipients, detail=detail, provider=provider,
                )
                return True, detail
            last_error = "%s send returned status=%s" % (provider, result.get("status") or "unknown")
            log_event(logger, logging.WARNING, "send_retry", attempt=attempt, error=last_error)
        except Exception as exc:
            last_error = str(exc)
            log_event(logger, logging.WARNING, "send_retry", attempt=attempt, error=last_error)
        if attempt < 2:
            time.sleep(10)

    append_send_log(
        {
            "date": date_label,
            "subject": subject,
            "recipients": recipients,
            "status": "failed",
            "detail": last_error,
            "provider": provider,
            "ts": utc_now().isoformat(),
        },
        logger,
    )
    log_event(logger, logging.ERROR, "send_failed", error=last_error, provider=provider)
    return False, last_error
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


def full_pipeline(
    config: AppConfig,
    feeds: list[FeedSource],
    args: argparse.Namespace,
    date_label: str,
    logger: logging.Logger,
) -> int:
    fetch_result = stage_fetch(config, feeds, date_label, logger)
    failure_ratio = 0.0
    if fetch_result.total_feeds:
        failure_ratio = len(fetch_result.failed_feeds) / float(fetch_result.total_feeds)
    if failure_ratio > config.fetch_fail_threshold:
        message = "Fetch aborted: %s/%s feeds failed" % (
            len(fetch_result.failed_feeds),
            fetch_result.total_feeds,
        )
        log_event(
            logger,
            logging.ERROR,
            "fetch_abort_threshold",
            failure_ratio=failure_ratio,
            message=message,
        )
        tg(failure_summary_message(message))
        return 2
    if not fetch_result.articles:
        message = "No articles fetched"
        log_event(logger, logging.ERROR, "fetch_empty", message=message)
        tg(failure_summary_message(message))
        return 2

    enriched = stage_enrich(fetch_result.articles, config, date_label, logger)
    curated, llm_failed = stage_curate(enriched, config, date_label, logger)

    html_body = compose_html(
        curated,
        fetch_result.articles,
        config,
        week_range_label(window_days=config.fetch_window_days),
    )
    write_html_outputs(date_label, html_body, logger)

    if args.fetch_only:
        status_code = 1 if fetch_result.failed_feeds else 0
        tg(success_summary_message(len(fetch_result.articles), curated, "fetch-only"))
        return status_code

    if args.dry_run:
        status = "dry-run"
        tg(success_summary_message(len(fetch_result.articles), curated, status))
        if llm_failed:
            return 2
        return 1 if fetch_result.failed_feeds else 0

    recipients = resolve_recipients(args.to, config)
    subject = "🤖 AI Weekly Digest — Week of %s [Issue #%s]" % (
        week_range_label(window_days=config.fetch_window_days),
        config.issue_number,
    )
    send_ok, send_detail = stage_send(
        config, recipients, subject, html_body, date_label, logger
    )
    if not send_ok:
        tg(failure_summary_message(send_detail))
        return 2

    tg(success_summary_message(len(fetch_result.articles), curated, send_detail))
    if llm_failed:
        return 2
    if fetch_result.failed_feeds:
        return 1
    return 0


def compose_only(config: AppConfig, logger: logging.Logger) -> int:
    curated_file = load_latest_artifact("curated")
    date_label = path_date_label(curated_file)
    curated = load_curated_stories(curated_file)
    articles: list[Article] = []
    matching_fetched = fetched_path(date_label)
    if matching_fetched.exists():
        articles = load_articles(matching_fetched)
    html_body = compose_html(
        curated,
        articles,
        config,
        week_range_label(window_days=config.fetch_window_days),
    )
    write_html_outputs(date_label, html_body, logger)
    log_event(
        logger, logging.INFO, "compose_only_complete", curated_file=str(curated_file)
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Weekly Digest newsletter pipeline v5"
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


def load_runtime_config(logger: logging.Logger) -> tuple[AppConfig, list[FeedSource]]:
    feeds = validate_feeds(load_yaml_file(FEEDS_FILE))
    config = validate_config(load_yaml_file(CONFIG_FILE))
    if not CURATE_PROMPT_FILE.exists():
        raise FileNotFoundError("Missing prompt file: %s" % CURATE_PROMPT_FILE)
    log_event(
        logger,
        logging.INFO,
        "config_loaded",
        feed_count=len(feeds),
        recipients=config.recipients,
        llm_endpoint=config.llm_endpoint,
    )
    return config, feeds


def main() -> int:
    args = parse_args()
    date_label = today_label()
    ensure_directories()
    logger = setup_logging(date_label)

    try:
        config, feeds = load_runtime_config(logger)
        cleanup_old_data_files(config.cleanup_retention_days, logger)

        if args.compose_only:
            return compose_only(config, logger)

        return full_pipeline(config, feeds, args, date_label, logger)
    except Exception as exc:
        if "logger" in locals():
            log_event(logger, logging.ERROR, "fatal_error", error=str(exc))
        tg(failure_summary_message(str(exc)))
        return 2


if __name__ == "__main__":
    sys.exit(main())
