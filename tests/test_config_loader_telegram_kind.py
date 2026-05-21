import unittest
from io import StringIO
from unittest.mock import patch

import yaml

from core.config_loader import ConfigLoader


class ConfigLoaderTelegramKindTests(unittest.TestCase):
    def _load(self, yaml_text: str):
        data = yaml.safe_load(StringIO(yaml_text))
        return ConfigLoader._validate_feeds(data)

    def test_kind_defaults_to_rss_when_absent(self):
        feeds = self._load("""
rss:
  - name: TechCrunch
    url: https://techcrunch.com/feed/
""")
        self.assertTrue(any(f.kind == "rss" for f in feeds))

    def test_kind_telegram_accepted(self):
        feeds = self._load("""
telegram:
  - name: AI News CN
    url: https://t.me/AI_News_CN
    kind: telegram
    skip_enrich: true
    max_items: 20
""")
        self.assertTrue(
            any(f.kind == "telegram" and f.name == "AI News CN" for f in feeds)
        )

    def test_telegram_kind_rejects_non_t_me_url(self):
        with self.assertRaises(ValueError) as ctx:
            self._load("""
telegram:
  - name: Not Telegram
    url: https://example.com/not-telegram
    kind: telegram
""")
        self.assertIn("t.me", str(ctx.exception))

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._load("""
rss:
  - name: Bogus
    url: https://example.com/feed
    kind: webhook
""")
        self.assertIn("kind", str(ctx.exception))

    def test_load_exposes_feed_sidecar_ad_keywords_on_config(self):
        feeds_doc = yaml.safe_load(StringIO("""
ad_keywords:
  - FooBar
  - 推广
telegram:
  - name: AI News CN
    url: https://t.me/AI_News_CN
    kind: telegram
"""))
        config_doc = yaml.safe_load(StringIO("""
email:
  provider: smtp
  recipients:
    - qa@example.com
llm:
  api_key: test-key
"""))
        with patch.object(ConfigLoader, "_load_yaml", side_effect=[feeds_doc, config_doc]):
            config, feeds = ConfigLoader().load(__import__("logging").getLogger("test"))
        self.assertEqual(config.ad_keywords, ["FooBar", "推广"])
        self.assertEqual(len(feeds), 1)


if __name__ == "__main__":
    unittest.main()
