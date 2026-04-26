"""
Utility package – re-exports all helpers for backward compatibility.
工具包 – 为向后兼容重新导出所有工具函数。

Sub-modules:
  utils.logging   – setup_logging, log_event, tg
  utils.text      – strip_html, truncate_text, escape_html
  utils.dates     – utc_now, today_label, week_range_label, parse_entry_datetime, ...
  utils.articles  – save/load_articles, deduplicate_articles, ...
  utils.http      – request_with_retry
  utils.images    – is_bad_image_url, url_looks_like_image
  utils.modules   – feedparser_module, trafilatura_module, ...
  utils.cleanup   – cleanup_old_data_files
"""

# Logging & notification
from core.utils.logging import setup_logging, log_event, tg  # noqa: F401

# Text processing
from core.utils.text import strip_html, truncate_text, escape_html  # noqa: F401

# Date / time
from core.utils.dates import (  # noqa: F401
    utc_now,
    today_label,
    week_range_label,
    parse_entry_datetime,
    article_datetime,
    article_sort_key,
)

# Article operations
from core.utils.articles import (  # noqa: F401
    normalize_title,
    title_tokens,
    title_similarity,
    better_article,
    deduplicate_articles,
    save_articles,
    load_articles,
)

# HTTP
from core.utils.http import request_with_retry  # noqa: F401

# Images
from core.utils.images import is_bad_image_url, url_looks_like_image  # noqa: F401

# Module loaders
from core.utils.modules import (  # noqa: F401
    load_module,
    feedparser_module,
    trafilatura_module,
    readability_document_class,
    email_client_class,
)

# Cleanup
from core.utils.cleanup import cleanup_old_data_files  # noqa: F401

# Path helpers (live in pipeline.paths, re-exported for backward compat)
from core.paths import (  # noqa: F401
    fetched_path,
    enriched_path,
    curated_path,
    output_html_path,
    ensure_directories,
)
