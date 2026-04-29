"""
Tests for core.utils.redact and EmailDispatcher recipient redaction.
core.utils.redact 与 EmailDispatcher 收件人脱敏的测试。

Designed to run with stdlib unittest (no external test deps required) and
also discoverable by pytest if available.
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

from core.utils.redact import mask_email, mask_recipients  # noqa: E402


SAMPLE_RAW = "alice@example.com"
SAMPLE_RAW_2 = "bob.smith@corp.test.io"


class MaskEmailTests(unittest.TestCase):
    def test_normal_email(self) -> None:
        self.assertEqual(mask_email("alice@example.com"), "a***@e***.com")

    def test_short_local_and_domain(self) -> None:
        self.assertEqual(mask_email("ab@x.io"), "a***@x***.io")

    def test_subdomain(self) -> None:
        # rpartition on dot keeps last segment as TLD
        self.assertEqual(mask_email("bob@mail.corp.io"), "b***@m***.io")

    def test_non_email_string(self) -> None:
        self.assertEqual(mask_email("not-an-email"), "***")

    def test_empty(self) -> None:
        self.assertEqual(mask_email(""), "")

    def test_whitespace_only(self) -> None:
        self.assertEqual(mask_email("   "), "")

    def test_non_string(self) -> None:
        self.assertEqual(mask_email(None), "")  # type: ignore[arg-type]
        self.assertEqual(mask_email(123), "")  # type: ignore[arg-type]

    def test_missing_local_or_domain(self) -> None:
        self.assertEqual(mask_email("@example.com"), "***")
        self.assertEqual(mask_email("alice@"), "***")

    def test_domain_without_dot(self) -> None:
        self.assertEqual(mask_email("a@localhost"), "a***@l***")


class MaskRecipientsTests(unittest.TestCase):
    def test_list(self) -> None:
        self.assertEqual(
            mask_recipients(["alice@example.com", "bob.smith@corp.test.io"]),
            ["a***@e***.com", "b***@c***.io"],
        )

    def test_drops_invalid_entries(self) -> None:
        self.assertEqual(
            mask_recipients(["alice@example.com", None, 5, "", "x"]),  # type: ignore[list-item]
            ["a***@e***.com", "***"],
        )

    def test_none(self) -> None:
        self.assertEqual(mask_recipients(None), [])  # type: ignore[arg-type]

    def test_no_raw_in_output(self) -> None:
        out = mask_recipients([SAMPLE_RAW, SAMPLE_RAW_2])
        joined = " ".join(out)
        self.assertNotIn(SAMPLE_RAW, joined)
        self.assertNotIn(SAMPLE_RAW_2, joined)


class EmailDispatcherRedactionTests(unittest.TestCase):
    """Verify EmailDispatcher does not leak raw recipients into log/artifact."""

    def setUp(self) -> None:
        # Import lazily so test file doesn't fail to collect on import errors.
        from core.email_dispatcher import EmailDispatcher
        from core import paths as paths_module

        self.tmp_dir = Path(__file__).resolve().parent / "_tmp_artifacts"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        # Redirect DATA_DIR so send-log.json is written in a sandbox.
        self._orig_data_dir = paths_module.DATA_DIR
        paths_module.DATA_DIR = self.tmp_dir
        # Also patch the symbol re-imported into email_dispatcher
        import core.email_dispatcher as ed
        self._orig_ed_data_dir = ed.DATA_DIR
        ed.DATA_DIR = self.tmp_dir

        self.send_log = self.tmp_dir / "send-log.json"
        if self.send_log.exists():
            self.send_log.unlink()

        cfg = mock.MagicMock()
        cfg.email_provider = "acs"
        cfg.acs_sender = "noreply@example.com"
        cfg.acs_connection_string = "endpoint=https://x;accesskey=fake"
        logger = logging.getLogger("test-dispatcher")
        logger.handlers.clear()
        self.dispatcher = EmailDispatcher(cfg, logger)
        self.EmailDispatcher = EmailDispatcher

    def tearDown(self) -> None:
        from core import paths as paths_module
        import core.email_dispatcher as ed
        paths_module.DATA_DIR = self._orig_data_dir
        ed.DATA_DIR = self._orig_ed_data_dir
        if self.send_log.exists():
            self.send_log.unlink()
        try:
            self.tmp_dir.rmdir()
        except OSError:
            pass

    def test_send_log_has_masked_only(self) -> None:
        recipients = [SAMPLE_RAW, SAMPLE_RAW_2]
        with mock.patch.object(
            self.EmailDispatcher,
            "_do_send",
            return_value={"status": "succeeded", "id": "test-id"},
        ):
            captured: list[str] = []
            with mock.patch("builtins.print", side_effect=lambda *a, **k: captured.append(" ".join(str(x) for x in a))):
                ok, _detail = self.dispatcher.send(
                    recipients, "subject", "<p>body</p>", "2026-04-28"
                )
        self.assertTrue(ok)
        # Artifact check
        self.assertTrue(self.send_log.exists())
        raw_text = self.send_log.read_text(encoding="utf-8")
        self.assertNotIn(SAMPLE_RAW, raw_text)
        self.assertNotIn(SAMPLE_RAW_2, raw_text)
        data = json.loads(raw_text)
        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertNotIn("recipients", entry)
        self.assertEqual(entry["recipients_count"], 2)
        self.assertEqual(
            entry["recipients_masked"], ["a***@e***.com", "b***@c***.io"]
        )
        # Stdout check
        joined = "\n".join(captured)
        self.assertNotIn(SAMPLE_RAW, joined)
        self.assertNotIn(SAMPLE_RAW_2, joined)
        self.assertIn("count=2", joined)


if __name__ == "__main__":
    unittest.main()
