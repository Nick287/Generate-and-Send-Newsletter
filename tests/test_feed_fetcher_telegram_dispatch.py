import datetime as dt
import logging
import unittest
from unittest.mock import patch

from core.feed_fetcher import FeedFetcher
from core.models import AppConfig, FeedSource


def _src(kind: str, name: str):
    return FeedSource(
        category="cat",
        name=name,
        url=(
            f"https://t.me/{name}" if kind == "telegram" else "https://example.com/feed"
        ),
        skip_enrich=True,
        max_items=10,
        kind=kind,
    )


def _config() -> AppConfig:
    return AppConfig(
        issue_number=1,
        recipients=[],
        acs_sender="",
        acs_connection_string="",
        email_provider="smtp",
        sendgrid_api_key="",
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_pass="",
        smtp_use_ssl=False,
        llm_endpoint="",
        llm_api_key="",
        llm_model="",
        llm_temperature=0.0,
        llm_max_tokens=1,
        llm_timeout=1,
        fetch_window_days=1,
        fetch_max_workers=1,
        fetch_max_per_feed=25,
        arxiv_cap_per_category=1,
        fetch_fail_threshold=1.0,
        enrich_top_candidates=1,
        enrich_fetch_delay=0.0,
        enrich_fetch_timeout=1,
        enrich_max_body_chars=1,
        cleanup_retention_days=1,
    )


class FeedFetcherDispatchTests(unittest.TestCase):
    def setUp(self):
        self.fetcher = FeedFetcher(_config(), logging.getLogger("test"))

    def test_telegram_kind_calls_telegram_fetch(self):
        sentinel = ([], None)
        with patch("core.feed_fetcher._telegram_fetch", return_value=sentinel) as m:
            result = self.fetcher._fetch_single(
                _src("telegram", "AI_News_CN"),
                dt.datetime(2026, 1, 1),
            )
        self.assertIs(result, sentinel)
        self.assertEqual(m.call_count, 1)

    def test_rss_kind_does_not_call_telegram_fetch(self):
        with patch("core.feed_fetcher._telegram_fetch") as m:
            try:
                self.fetcher._fetch_single(
                    _src("rss", "ExampleFeed"),
                    dt.datetime(2026, 1, 1),
                )
            except Exception:
                pass
        m.assert_not_called()


if __name__ == "__main__":
    unittest.main()
