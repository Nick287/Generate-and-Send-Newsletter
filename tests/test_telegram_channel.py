import datetime as dt
import logging
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.feeds.telegram_channel import fetch, parse_html, DEFAULT_AD_KEYWORDS
from core.models import AppConfig, FeedSource

FIXTURE = Path(__file__).parent / "fixtures" / "telegram_synthetic_sample.html"


def _src(
    *,
    category: str = "telegram",
    name: str = "AI News CN",
    url: str = "https://t.me/AI_News_CN",
    skip_enrich: bool = True,
    max_items: int | None = 20,
    kind: str = "telegram",
) -> FeedSource:
    return FeedSource(
        category=category,
        name=name,
        url=url,
        skip_enrich=skip_enrich,
        max_items=max_items,
        kind=kind,
    )


def _config(ad_keywords: list[str] | None = None) -> AppConfig:
    return AppConfig(
        issue_number=1,
        recipients=["qa@example.com"],
        acs_sender="",
        acs_connection_string="",
        email_provider="smtp",
        sendgrid_api_key="",
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_pass="",
        smtp_use_ssl=False,
        llm_endpoint="https://example.com/v1/chat/completions",
        llm_api_key="test-key",
        llm_model="test-model",
        llm_temperature=0.0,
        llm_max_tokens=256,
        llm_timeout=10,
        fetch_window_days=1,
        fetch_max_workers=1,
        fetch_max_per_feed=25,
        arxiv_cap_per_category=1,
        fetch_fail_threshold=1.0,
        enrich_top_candidates=1,
        enrich_fetch_delay=0.0,
        enrich_fetch_timeout=1,
        enrich_max_body_chars=200,
        cleanup_retention_days=1,
        ad_keywords=ad_keywords or [],
    )


class TelegramChannelTests(unittest.TestCase):
    def setUp(self):
        self.html = FIXTURE.read_text(encoding="utf-8")
        self.logger = logging.getLogger("test")

    def test_parse_synthetic_fixture_yields_20_articles_minus_ads(self):
        articles = parse_html(
            self.html, _src(), channel="AI_News_CN", ad_keywords=DEFAULT_AD_KEYWORDS
        )
        self.assertEqual(len(articles), 19)

    def test_pinned_and_service_messages_are_skipped(self):
        articles = parse_html(
            self.html, _src(), channel="AI_News_CN", ad_keywords=DEFAULT_AD_KEYWORDS
        )
        for a in articles:
            self.assertNotIn("service", (a.raw_summary or "").lower()[:50])
            self.assertNotIn("pinned", (a.raw_summary or "").lower()[:50])

    def test_post_link_construction(self):
        articles = parse_html(
            self.html, _src(), channel="AI_News_CN", ad_keywords=DEFAULT_AD_KEYWORDS
        )
        self.assertTrue(
            any(a.link == "https://t.me/AI_News_CN/11001" for a in articles),
            f"links: {[a.link for a in articles[:5]]}",
        )

    def test_image_url_extracted_from_background_style(self):
        articles = parse_html(
            self.html, _src(), channel="AI_News_CN", ad_keywords=DEFAULT_AD_KEYWORDS
        )
        with_images = [a for a in articles if a.image_url]
        self.assertGreaterEqual(len(with_images), 3)
        for a in with_images:
            image_url = a.image_url
            self.assertIsNotNone(image_url)
            assert image_url is not None
            self.assertTrue(image_url.startswith("http"))
            self.assertEqual(a.og_image, image_url)

    def test_skip_enrich_is_always_true(self):
        articles = parse_html(
            self.html,
            _src(skip_enrich=False),
            channel="AI_News_CN",
            ad_keywords=DEFAULT_AD_KEYWORDS,
        )
        self.assertTrue(articles)
        for a in articles:
            self.assertTrue(a.skip_enrich)

    def test_cap_is_20_even_with_more_input(self):
        wrappers = []
        for i in range(25):
            wrappers.append(f"""
              <div class="tgme_widget_message_wrap">
                <div class="tgme_widget_message" data-post="AI_News_CN/{20000 + i}">
                  <time datetime="2026-05-20T12:00:00+00:00">12:00</time>
                  <div class="tgme_widget_message_text">post number {i}</div>
                </div>
              </div>
            """)
        html = "<html><body>" + "".join(wrappers) + "</body></html>"
        articles = parse_html(
            html, _src(), channel="AI_News_CN", ad_keywords=DEFAULT_AD_KEYWORDS
        )
        self.assertLessEqual(len(articles), 20)

    def test_source_max_items_can_lower_twenty_cap(self):
        wrappers = []
        for i in range(10):
            wrappers.append(f"""
              <div class="tgme_widget_message_wrap">
                <div class="tgme_widget_message" data-post="AI_News_CN/{30000 + i}">
                  <time datetime="2026-05-20T12:00:00+00:00">12:00</time>
                  <div class="tgme_widget_message_text">post number {i}</div>
                </div>
              </div>
            """)
        html = "<html><body>" + "".join(wrappers) + "</body></html>"
        articles = parse_html(
            html, _src(max_items=5), channel="AI_News_CN", ad_keywords=DEFAULT_AD_KEYWORDS
        )
        self.assertEqual(len(articles), 5)

    def test_data_view_pinned_messages_are_skipped(self):
        html = """<html><body>
          <div class="tgme_widget_message_wrap">
            <div class="tgme_widget_message" data-post="AI_News_CN/9101" data-view="pinned">
              <time datetime="2026-05-20T12:00:00+00:00">12:00</time>
              <div class="tgme_widget_message_text">pinned operational notice</div>
            </div>
          </div>
          <div class="tgme_widget_message_wrap">
            <div class="tgme_widget_message" data-post="AI_News_CN/9102">
              <time datetime="2026-05-20T12:01:00+00:00">12:01</time>
              <div class="tgme_widget_message_text">regular news item</div>
            </div>
          </div>
        </body></html>"""
        articles = parse_html(
            html, _src(), channel="AI_News_CN", ad_keywords=DEFAULT_AD_KEYWORDS
        )
        self.assertEqual(len(articles), 1)
        self.assertIn("regular news", articles[0].raw_summary)

    def test_non_http_image_urls_are_ignored(self):
        html = """<html><body>
          <div class="tgme_widget_message_wrap">
            <div class="tgme_widget_message" data-post="AI_News_CN/9201">
              <time datetime="2026-05-20T12:00:00+00:00">12:00</time>
              <div class="tgme_widget_message_text">news with unsafe image</div>
              <a class="tgme_widget_message_photo_wrap" style="background-image:url('javascript:alert(1)')"></a>
            </div>
          </div>
        </body></html>"""
        articles = parse_html(
            html, _src(), channel="AI_News_CN", ad_keywords=DEFAULT_AD_KEYWORDS
        )
        self.assertEqual(len(articles), 1)
        self.assertIsNone(articles[0].image_url)

    def test_ad_filter_strips_blacklist_substring_case_insensitive(self):
        html = """<html><body>
          <div class="tgme_widget_message_wrap">
            <div class="tgme_widget_message" data-post="AI_News_CN/9001">
              <time datetime="2026-05-20T12:00:00+00:00">12:00</time>
              <div class="tgme_widget_message_text">Visit OAIBEST.com today!</div>
            </div>
          </div>
          <div class="tgme_widget_message_wrap">
            <div class="tgme_widget_message" data-post="AI_News_CN/9002">
              <time datetime="2026-05-20T12:00:00+00:00">12:00</time>
              <div class="tgme_widget_message_text">DeepSeek released v3 today.</div>
            </div>
          </div>
        </body></html>"""
        articles = parse_html(
            html, _src(), channel="AI_News_CN", ad_keywords=DEFAULT_AD_KEYWORDS
        )
        self.assertEqual(len(articles), 1)
        self.assertIn("DeepSeek", articles[0].raw_summary)

    def test_fetch_uses_config_ad_keywords_union_with_defaults(self):
        html = """<html><body>
          <div class="tgme_widget_message_wrap">
            <div class="tgme_widget_message" data-post="AI_News_CN/9301">
              <time datetime="2026-05-20T12:00:00+00:00">12:00</time>
              <div class="tgme_widget_message_text">Sponsored by FooBar Capital</div>
            </div>
          </div>
          <div class="tgme_widget_message_wrap">
            <div class="tgme_widget_message" data-post="AI_News_CN/9302">
              <time datetime="2026-05-20T12:01:00+00:00">12:01</time>
              <div class="tgme_widget_message_text">Real product news.</div>
            </div>
          </div>
        </body></html>"""
        response = Mock()
        response.text = html
        with patch("core.feeds.telegram_channel.request_with_retry", return_value=response):
            articles, err = fetch(
                _src(),
                dt.datetime(2026, 1, 1),
                _config(["FooBar"]),
                self.logger,
            )
        self.assertIsNone(err)
        self.assertEqual(len(articles), 1)
        self.assertIn("Real product", articles[0].raw_summary)

    def test_ad_filter_custom_keywords_union_with_defaults(self):
        html = """<html><body>
          <div class="tgme_widget_message_wrap">
            <div class="tgme_widget_message" data-post="AI_News_CN/9003">
              <time datetime="2026-05-20T12:00:00+00:00">12:00</time>
              <div class="tgme_widget_message_text">Sponsored by FooBar Capital</div>
            </div>
          </div>
          <div class="tgme_widget_message_wrap">
            <div class="tgme_widget_message" data-post="AI_News_CN/9004">
              <time datetime="2026-05-20T12:00:00+00:00">12:00</time>
              <div class="tgme_widget_message_text">Real news content.</div>
            </div>
          </div>
        </body></html>"""
        custom = list(DEFAULT_AD_KEYWORDS) + ["FooBar"]
        articles = parse_html(
            html, _src(), channel="AI_News_CN", ad_keywords=tuple(custom)
        )
        self.assertEqual(len(articles), 1)
        self.assertIn("Real news", articles[0].raw_summary)


if __name__ == "__main__":
    unittest.main()
