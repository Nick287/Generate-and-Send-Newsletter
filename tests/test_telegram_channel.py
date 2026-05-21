import logging
import unittest
from pathlib import Path

from core.feeds.telegram_channel import fetch, parse_html, DEFAULT_AD_KEYWORDS
from core.models import FeedSource

FIXTURE = Path(__file__).parent / "fixtures" / "telegram_synthetic_sample.html"


def _src(**overrides):
    base = dict(
        category="telegram",
        name="AI News CN",
        url="https://t.me/AI_News_CN",
        skip_enrich=True,
        max_items=20,
        kind="telegram",
    )
    base.update(overrides)
    return FeedSource(**base)


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
            self.assertTrue(a.image_url.startswith("http"))
            self.assertEqual(a.og_image, a.image_url)

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
