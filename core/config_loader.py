"""
ConfigLoader — loads and validates config.yaml and feeds.yaml.
ConfigLoader — 加载并校验 config.yaml 和 feeds.yaml 配置文件。

Responsibilities:
职责：
- Read YAML files safely | 安全读取YAML文件
- Validate all required fields and value ranges | 校验所有必填字段和值范围
- Return typed AppConfig and FeedSource list    | 返回类型化的 AppConfig 和 FeedSource 列表
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from core.models import AppConfig, FeedSource
from core.paths import (
    FEEDS_FILE,
    CONFIG_FILE,
    CURATE_PROMPT_FILE,
    DEFAULT_LLM_ENDPOINT,
    DEFAULT_LLM_MODEL,
    DEFAULT_ACS_SENDER,
)
from core.utils import log_event


class ConfigLoader:
    """Loads and validates runtime configuration from YAML files.
    从YAML文件加载并校验运行时配置。
    """

    def __init__(self) -> None:
        pass

    # ── public API ───────────────────────────────────────────────────────────
    def load(self, logger: logging.Logger) -> tuple[AppConfig, list[FeedSource]]:
        print("--- Step: Loading configuration files ---")
        feeds = self._validate_feeds(self._load_yaml(FEEDS_FILE))
        config = self._validate_config(self._load_yaml(CONFIG_FILE))
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
        print("    Loaded %d feeds, %d recipients" % (len(feeds), len(config.recipients)))
        return config, feeds

    # ── internal helpers | 内部工具方法 ─────────────────────────────────────
    @staticmethod
    def _load_yaml(path: Path) -> Any:
        """Read and parse a YAML file safely. | 安全读取并解析YAML文件。"""
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError("Failed to read %s: %s" % (path, exc)) from exc

    @staticmethod
    def _validate_feeds(doc: Any) -> list[FeedSource]:
        """Validate feeds.yaml structure and return typed FeedSource list.
        校验 feeds.yaml 结构并返回类型化的 FeedSource 列表。
        """
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
                        "feeds.yaml entry %s[%s] is missing a valid name" % (category, index)
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

    @staticmethod
    def _validate_config(doc: Any) -> AppConfig:
        """Validate config.yaml and return a fully-populated AppConfig.
        校验 config.yaml 并返回完整填充的 AppConfig 对象。

        Validates: issue_number, email settings, LLM params, fetch/enrich/cleanup params.
        校验内容：期刊号、邮件设置、LLM参数、抓取/充实/清理参数。
        """
        if not isinstance(doc, dict):
            raise ValueError("config.yaml must be a mapping")

        issue_number = doc.get("issue_number", 1)
        email_cfg = doc.get("email", {}) if isinstance(doc.get("email"), dict) else {}
        llm = doc.get("llm", {})
        fetch = doc.get("fetch", {})
        enrich = doc.get("enrich", {})
        cleanup = doc.get("cleanup", {})

        # ── Email: YAML first, then env-var overrides ──────────────────────
        # 邮件配置：先读YAML，再用环境变量覆盖
        recipients = email_cfg.get("recipients", doc.get("recipients"))
        # TO_ADDRS env var (compatible with newsletter_git_action.py .env)
        # TO_ADDRS 环境变量（兼容 newsletter_git_action.py 的 .env 格式）
        env_to = os.environ.get("TO_ADDRS", "")
        if env_to.strip():
            recipients = [a.strip() for a in env_to.split(",") if a.strip()]

        acs_sender = email_cfg.get("acs_sender", doc.get("acs_sender", DEFAULT_ACS_SENDER))
        acs_connection_string = (
            os.environ.get("ACS_CONNECTION_STRING", "")
            or email_cfg.get("acs_connection_string", "")
            or ""
        )
        email_provider = (email_cfg.get("provider") or "acs").lower().strip()
        sendgrid_api_key = (
            os.environ.get("SENDGRID_API_KEY", "")
            or email_cfg.get("sendgrid_api_key", "")
            or ""
        )

        # SMTP settings: env vars override YAML (compatible with .env)
        # SMTP设置：环境变量覆盖YAML（兼容 .env 文件）
        smtp_host = os.environ.get("SMTP_HOST", "") or email_cfg.get("smtp_host", "") or ""
        smtp_port = int(
            os.environ.get("SMTP_PORT", "")
            or email_cfg.get("smtp_port", 587)
            or 587
        )
        smtp_user = (
            os.environ.get("SENDER_USERNAME", "")
            or os.environ.get("SMTP_USER", "")
            or email_cfg.get("smtp_user", "")
            or ""
        )
        smtp_pass = (
            os.environ.get("SENDER_PASSWORD", "")
            or os.environ.get("SMTP_PASS", "")
            or email_cfg.get("smtp_pass", "")
            or ""
        )
        smtp_use_ssl = bool(email_cfg.get("smtp_use_ssl", False))
        # FROM_ALIAS env var (used as sender display name for SMTP)
        # FROM_ALIAS 环境变量（SMTP发件人显示名称）
        from_alias = os.environ.get("FROM_ALIAS", "") or ""

        # Auto-detect SMTP provider when SMTP env vars are set but provider is default
        # 当设置了SMTP环境变量但provider为默认值时，自动切换为SMTP提供商
        if smtp_host and smtp_user and email_provider == "acs":
            email_provider = "smtp"

        if not isinstance(issue_number, int) or issue_number < 1:
            raise ValueError("config.yaml issue_number must be a positive integer")
        if (
            not isinstance(recipients, list)
            or not recipients
            or not all(isinstance(item, str) and item.strip() for item in recipients)
        ):
            raise ValueError(
                "config recipients must be a non-empty list of strings "
                "(set TO_ADDRS env var, or email.recipients in config.yaml)"
            )
        if not isinstance(acs_sender, str):
            acs_sender = ""
        if email_provider == "acs" and not acs_sender.strip():
            raise ValueError("config.yaml email.acs_sender required when provider=acs")
        if not isinstance(llm, dict):
            llm = {}
        if not isinstance(fetch, dict):
            fetch = {}
        if not isinstance(enrich, dict):
            enrich = {}
        if not isinstance(cleanup, dict):
            cleanup = {}

        # ── LLM: YAML first, then env-var overrides ───────────────────────
        # LLM配置：先读YAML，再用环境变量覆盖
        endpoint = (
            os.environ.get("AZURE_OPENAI_ENDPOINT", "")
            or llm.get("endpoint", "")
            or DEFAULT_LLM_ENDPOINT
        )
        # Append /chat/completions if endpoint looks like a bare Azure OpenAI base URL
        # 如果端点看起来是裸Azure OpenAI基础URL，自动追加 /chat/completions
        if endpoint and "cognitiveservices.azure.com" in endpoint and "/chat/completions" not in endpoint:
            endpoint = endpoint.rstrip("/") + "/openai/deployments/gpt-4o/chat/completions?api-version=2024-12-01-preview"
        api_key = (
            os.environ.get("AZURE_OPENAI_TOKEN", "")
            or os.environ.get("LLM_API_KEY", "")
            or os.environ.get("OPENAI_API_KEY", "")
            or llm.get("api_key", "")
        )
        model = llm.get("model", DEFAULT_LLM_MODEL)
        fallback_endpoint = llm.get("fallback_endpoint", "") or ""
        fallback_api_key = llm.get("fallback_api_key", "") or ""
        fallback_model = llm.get("fallback_model", "") or ""
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
            llm_fallback_endpoint=str(fallback_endpoint).strip(),
            llm_fallback_api_key=str(fallback_api_key).strip(),
            llm_fallback_model=str(fallback_model).strip(),
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
            from_alias=from_alias,
        )
