"""
Data models (dataclasses) for the newsletter pipeline.
新闻简报流水线的数据模型（数据类）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class FeedSource:
    """Represents a single RSS/Atom feed source.
    表示一个RSS/Atom订阅源。
    """
    category: str
    name: str
    url: str
    max_items: Optional[int] = None
    skip_enrich: bool = False


@dataclass
class AppConfig:
    """Application configuration loaded from config.yaml.
    从 config.yaml 加载的应用配置。
    """
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
    llm_fallback_endpoint: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""
    from_alias: str = ""
    template_version: str = "v7"
    curate_prompt_version: str = "v5"


@dataclass
class Article:
    """Represents a single news article throughout the pipeline.
    表示流水线中的一篇新闻文章。
    """
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
    """Result of the feed-fetching stage.
    RSS抓取阶段的结果。
    """
    articles: list[Article]
    failed_feeds: list[str]
    total_feeds: int
    reused: bool


@dataclass
class StageOutcome:
    """Generic outcome descriptor for any pipeline stage.
    流水线任意阶段的通用结果描述。
    """
    critical_failure: bool = False
    partial_failure: bool = False
    message: str = ""
