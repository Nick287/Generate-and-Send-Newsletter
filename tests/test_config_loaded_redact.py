"""
Test that ConfigLoader's config_loaded log event redacts recipient addresses.
配置加载日志事件需脱敏收件人地址。
"""

from __future__ import annotations

import json
import logging
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ConfigLoadedRedactionTests(unittest.TestCase):
    def test_log_event_redacts_recipients(self) -> None:
        from core import config_loader as cl

        captured: dict = {}

        def fake_log_event(logger, level, event, **kwargs):
            captured.update(kwargs)
            captured["_event"] = event

        cfg = mock.Mock()
        cfg.recipients = ["alice@example.com", "bob@corp.test"]
        cfg.llm_endpoint = "https://llm.example/"

        with mock.patch.object(cl, "log_event", side_effect=fake_log_event):
            cl.log_event(
                logging.getLogger("t"), logging.INFO, "config_loaded",
                feed_count=1,
                recipients_count=len(cfg.recipients),
                recipients_masked=cl.mask_recipients(cfg.recipients),
                llm_endpoint=cfg.llm_endpoint,
            )

        self.assertEqual(captured["_event"], "config_loaded")
        self.assertEqual(captured["recipients_count"], 2)
        dumped = json.dumps(captured)
        self.assertNotIn("alice@example.com", dumped)
        self.assertNotIn("bob@corp.test", dumped)
        self.assertIn("recipients_masked", captured)


if __name__ == "__main__":
    unittest.main()
