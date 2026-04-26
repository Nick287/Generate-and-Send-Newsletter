"""
Text processing helpers: HTML stripping, truncation, escaping.
文本处理工具：去HTML、截断、转义。
"""

from __future__ import annotations

import html
import re


def strip_html(raw: str) -> str:
    """Remove HTML tags and decode entities."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def truncate_text(text: str, limit: int) -> str:
    """Truncate text to limit chars, breaking at word boundary."""
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0].strip() + "…"


def escape_html(value: str) -> str:
    """HTML-escape a string for safe template insertion."""
    return html.escape(value or "", quote=True)
