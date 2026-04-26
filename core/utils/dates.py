"""
Date and time helpers.
日期与时间工具。
"""

from __future__ import annotations

import datetime as dt
import email.utils
from typing import Any, Optional

from core.models import Article


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def today_label(now: Optional[dt.datetime] = None) -> str:
    current = now or utc_now()
    return current.date().isoformat()


def week_range_label(now: Optional[dt.datetime] = None, window_days: int = 7) -> str:
    """Return human-readable date range string, e.g. 'Apr 18 – Apr 24, 2026'."""
    current = now or utc_now()
    start = (current - dt.timedelta(days=max(window_days - 1, 0))).date()
    end = current.date()
    if start.year == end.year:
        return "%s – %s" % (start.strftime("%b %d"), end.strftime("%b %d, %Y"))
    return "%s – %s" % (start.strftime("%b %d, %Y"), end.strftime("%b %d, %Y"))


def parse_entry_datetime(entry: Any) -> Optional[dt.datetime]:
    """Parse datetime from an RSS feed entry, trying multiple field formats."""
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
    """Convert article.published_date string to UTC datetime."""
    if not article.published_date:
        return None
    try:
        return dt.datetime.fromisoformat(
            article.published_date.replace("Z", "+00:00")
        ).astimezone(dt.timezone.utc)
    except Exception:
        return None


def article_sort_key(article: Article) -> tuple[int, float, float, int, str]:
    """Multi-factor sort key: has_date > timestamp > pre_score > summary_length > title."""
    published = article_datetime(article)
    has_date = 0 if published is not None else 1
    timestamp = -published.timestamp() if published is not None else float("inf")
    pre_score = -(article.pre_score if article.pre_score is not None else -1.0)
    summary_length = -len(article.raw_summary or "")
    return (has_date, timestamp, pre_score, summary_length, article.title.lower())
