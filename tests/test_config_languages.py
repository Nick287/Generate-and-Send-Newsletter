"""Tests for `compose.languages` config parsing and back-compat with `compose.bilingual`."""

from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@contextmanager
def _temp_config(compose_block: dict[str, Any]) -> Iterator[tuple[Path, Path]]:
    doc = {
        "issue_number": 1,
        "email": {
            "provider": "acs",
            "recipients": ["x@y.com"],
            "acs_sender": "DoNotReply@a.b.azurecomm.net",
        },
        "llm": {
            "endpoint": "https://llm.example.com/v1/chat/completions",
            "api_key": "sk-test",
            "model": "test-model",
        },
        "compose": compose_block,
    }
    cfg_path: Path | None = None
    feeds_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            yaml.safe_dump(doc, tmp)
            cfg_path = Path(tmp.name)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp_feeds:
            yaml.safe_dump(
                {"news": [{"name": "x", "url": "https://e.com/rss"}]}, tmp_feeds
            )
            feeds_path = Path(tmp_feeds.name)
        yield cfg_path, feeds_path
    finally:
        if cfg_path is not None:
            cfg_path.unlink(missing_ok=True)
        if feeds_path is not None:
            feeds_path.unlink(missing_ok=True)


def _load(compose_block: dict[str, Any]) -> Any:
    from core.config_loader import ConfigLoader

    with _temp_config(compose_block) as (cfg_path, feeds_path):
        with mock.patch("core.config_loader.CONFIG_FILE", cfg_path):
            with mock.patch("core.config_loader.FEEDS_FILE", feeds_path):
                cfg, _ = ConfigLoader().load(logging.getLogger("test"))
    return cfg


class TestComposeLanguagesParsing(unittest.TestCase):

    def test_compose_languages_field_parses_list(self) -> None:
        cfg = _load({"languages": ["zh"], "translate_prompt_version": "v1"})
        self.assertEqual(cfg.compose_languages, ["zh"])
        self.assertTrue(cfg.compose_bilingual)

    def test_compose_languages_lowercases_and_dedupes(self) -> None:
        cfg = _load(
            {"languages": ["ZH", "zh", " ZH "], "translate_prompt_version": "v1"}
        )
        self.assertEqual(cfg.compose_languages, ["zh"])

    def test_compose_languages_takes_precedence_over_bilingual_true(self) -> None:
        cfg = _load(
            {"bilingual": True, "languages": ["zh"], "translate_prompt_version": "v1"}
        )
        self.assertEqual(cfg.compose_languages, ["zh"])
        self.assertTrue(cfg.compose_bilingual)

    def test_bilingual_true_no_languages_maps_to_zh(self) -> None:
        cfg = _load({"bilingual": True, "translate_prompt_version": "v1"})
        self.assertEqual(cfg.compose_languages, ["zh"])
        self.assertTrue(cfg.compose_bilingual)

    def test_bilingual_false_no_languages_yields_empty(self) -> None:
        cfg = _load({"bilingual": False, "translate_prompt_version": "v1"})
        self.assertEqual(cfg.compose_languages, [])
        self.assertFalse(cfg.compose_bilingual)

    def test_languages_overrides_bilingual_false_with_warning(self) -> None:
        with self.assertLogs("ai-newsletter-config", level="WARNING") as captured:
            cfg = _load(
                {
                    "bilingual": False,
                    "languages": ["zh"],
                    "translate_prompt_version": "v1",
                }
            )
        self.assertEqual(cfg.compose_languages, ["zh"])
        self.assertTrue(cfg.compose_bilingual)
        joined = "\n".join(captured.output)
        self.assertIn("compose_config_conflict", joined)

    def test_compose_languages_invalid_type_raises(self) -> None:
        with self.assertRaises(ValueError) as cm:
            _load({"languages": "zh", "translate_prompt_version": "v1"})
        self.assertIn("compose.languages", str(cm.exception))

    def test_compose_languages_missing_prompt_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            _load(
                {
                    "languages": ["xx"],
                    "translate_prompt_version": "v1",
                }
            )


if __name__ == "__main__":
    unittest.main()
