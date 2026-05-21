import datetime as dt
import logging
import unittest
from unittest.mock import patch

from core.feed_fetcher import FeedFetcher
from core.models import FeedSource


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


class FeedFetcherDispatchTests(unittest.TestCase):
    def setUp(self):
        class _Cfg:
            ad_keywords = None
            fetch_max_per_feed = 25

        self.fetcher = FeedFetcher(_Cfg(), logging.getLogger("test"))

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
