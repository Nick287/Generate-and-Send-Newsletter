import unittest
from io import StringIO

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

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._load("""
rss:
  - name: Bogus
    url: https://example.com/feed
    kind: webhook
""")
        self.assertIn("kind", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
