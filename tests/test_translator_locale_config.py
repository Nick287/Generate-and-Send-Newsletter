"""Tests for `core.translator.LocaleConfig` factories and `Translator(locale=...)` integration.

Covers issue #28 multi-locale Translator generalization:
  * Each `LocaleConfig.{zh, ja, ko, vi}()` factory returns expected validation
    parameters (script regex, min-ratio, length band, date format).
  * Translator accepts a `locale=` kwarg and exposes it via `self.locale`.
  * `_LOCALE_FACTORIES` in `core.html_composer` covers the same locales.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestLocaleConfigFactories(unittest.TestCase):
    """Each factory must return the agreed validation parameters."""

    def test_zh_factory(self) -> None:
        from core.translator import LocaleConfig

        cfg = LocaleConfig.zh()
        self.assertEqual(cfg.code, "zh")
        self.assertEqual(cfg.length_band, (0.25, 1.2))
        self.assertEqual(cfg.date_format, "%Y年%m月%d日")
        self.assertGreater(cfg.min_script_ratio, 0.0)
        self.assertIsNotNone(cfg.script_pattern.search("中文测试"))
        self.assertIsNone(cfg.script_pattern.search("english only"))

    def test_ja_factory(self) -> None:
        from core.translator import LocaleConfig

        cfg = LocaleConfig.ja()
        self.assertEqual(cfg.code, "ja")
        self.assertEqual(cfg.length_band, (0.25, 1.2))
        self.assertEqual(cfg.date_format, "%Y年%m月%d日")
        self.assertIsNotNone(cfg.script_pattern.search("こんにちは"))
        self.assertIsNotNone(cfg.script_pattern.search("カタカナ"))
        self.assertIsNotNone(cfg.script_pattern.search("漢字"))
        self.assertIsNone(cfg.script_pattern.search("english only"))

    def test_ko_factory(self) -> None:
        from core.translator import LocaleConfig

        cfg = LocaleConfig.ko()
        self.assertEqual(cfg.code, "ko")
        self.assertEqual(cfg.length_band, (0.40, 1.4))
        self.assertEqual(cfg.date_format, "%Y년%m월%d일")
        self.assertIsNotNone(cfg.script_pattern.search("한국어"))
        self.assertIsNone(cfg.script_pattern.search("english only"))
        self.assertIsNone(
            cfg.script_pattern.search("漢字"),
            "Korean regex must NOT match CJK characters (Hangul-only).",
        )

    def test_vi_factory(self) -> None:
        from core.translator import LocaleConfig

        cfg = LocaleConfig.vi()
        self.assertEqual(cfg.code, "vi")
        self.assertEqual(cfg.length_band, (0.80, 1.6))
        self.assertEqual(cfg.date_format, "%d/%m/%Y")
        self.assertEqual(
            cfg.min_script_ratio,
            0.0,
            "Vietnamese skips the script-ratio gate (uses extended Latin).",
        )
        self.assertIsNotNone(cfg.script_pattern.search("Tiếng Việt"))

    def test_factories_return_frozen_instances(self) -> None:
        from dataclasses import FrozenInstanceError

        from core.translator import LocaleConfig

        for cfg in (
            LocaleConfig.zh(),
            LocaleConfig.ja(),
            LocaleConfig.ko(),
            LocaleConfig.vi(),
        ):
            with self.assertRaises(FrozenInstanceError):
                cfg.code = "mutated"  # type: ignore[misc]


class TestTranslatorAcceptsLocale(unittest.TestCase):
    """Translator generalization: must accept a `locale=` kwarg."""

    def test_translator_stores_locale(self) -> None:
        from unittest.mock import MagicMock

        from core.translator import LocaleConfig, Translator

        llm = MagicMock()
        logger = MagicMock()
        locale = LocaleConfig.ko()

        translator = Translator(
            llm_client=llm,
            prompt_version="v1",
            logger=logger,
            locale=locale,
        )
        self.assertIs(translator._locale, locale)

    def test_translator_defaults_to_zh_locale_when_omitted(self) -> None:
        """Back-compat: omitting `locale` keeps legacy zh behavior."""
        from unittest.mock import MagicMock

        from core.translator import LocaleConfig, Translator

        llm = MagicMock()
        logger = MagicMock()

        translator = Translator(llm_client=llm, prompt_version="v1", logger=logger)
        self.assertEqual(translator._locale.code, LocaleConfig.zh().code)


class TestComposerLocaleFactoryRegistry(unittest.TestCase):
    """`core.html_composer._LOCALE_FACTORIES` must cover the same 4 locales."""

    def test_locale_factories_registry_complete(self) -> None:
        from core.html_composer import _LOCALE_FACTORIES

        self.assertIn("zh", _LOCALE_FACTORIES)
        self.assertIn("ja", _LOCALE_FACTORIES)
        self.assertIn("ko", _LOCALE_FACTORIES)
        self.assertIn("vi", _LOCALE_FACTORIES)

    def test_locale_factories_produce_matching_codes(self) -> None:
        from core.html_composer import _LOCALE_FACTORIES

        for code, factory in _LOCALE_FACTORIES.items():
            cfg = factory()
            self.assertEqual(
                cfg.code,
                code,
                "Factory key %r must produce LocaleConfig.code=%r, got %r"
                % (code, code, cfg.code),
            )


class TestTranslatorMergeUsesLocaleSuffixedKeys(unittest.TestCase):
    """Regression: `_merge` must read `title_{locale.code}` / `summary_{locale.code}`.

    Before the Oracle Option-B fix `_merge` hardcoded `title_zh`/`summary_zh`,
    so a `Translator(locale=LocaleConfig.ko())` would silently drop every
    Korean translation. This test confirms (a) the per-locale lookup works,
    and (b) feeding zh-suffixed keys to a non-zh translator raises
    `TranslationFailed` (no cross-locale fall-through).
    """

    def _make_translator(self, locale_code: str):
        from unittest.mock import MagicMock

        from core.translator import LocaleConfig, Translator

        factory = {
            "zh": LocaleConfig.zh,
            "ja": LocaleConfig.ja,
            "ko": LocaleConfig.ko,
            "vi": LocaleConfig.vi,
        }[locale_code]
        return Translator(
            llm_client=MagicMock(),
            prompt_version="v1",
            logger=MagicMock(),
            locale=factory(),
        )

    def test_merge_reads_locale_suffixed_keys_for_ko(self) -> None:
        translator = self._make_translator("ko")
        originals = [{"id": "s1", "title": "EN", "summary": "EN summary"}]
        response = {
            "stories": [
                {"id": "s1", "title_ko": "한국어 제목", "summary_ko": "한국어 요약"}
            ]
        }
        merged = translator._merge(originals, response)
        self.assertEqual(merged[0]["title"], "한국어 제목")
        self.assertEqual(merged[0]["summary"], "한국어 요약")

    def test_merge_reads_locale_suffixed_keys_for_ja(self) -> None:
        translator = self._make_translator("ja")
        originals = [{"id": "s1", "title": "EN", "summary": "EN summary"}]
        response = {
            "stories": [
                {"id": "s1", "title_ja": "日本語タイトル", "summary_ja": "日本語要約"}
            ]
        }
        merged = translator._merge(originals, response)
        self.assertEqual(merged[0]["title"], "日本語タイトル")
        self.assertEqual(merged[0]["summary"], "日本語要約")

    def test_merge_reads_locale_suffixed_keys_for_vi(self) -> None:
        translator = self._make_translator("vi")
        originals = [{"id": "s1", "title": "EN", "summary": "EN summary"}]
        response = {
            "stories": [
                {"id": "s1", "title_vi": "Tiêu đề tiếng Việt", "summary_vi": "Tóm tắt"}
            ]
        }
        merged = translator._merge(originals, response)
        self.assertEqual(merged[0]["title"], "Tiêu đề tiếng Việt")
        self.assertEqual(merged[0]["summary"], "Tóm tắt")

    def test_merge_rejects_wrong_locale_keys_for_ko_translator(self) -> None:
        from core.translator import TranslationFailed

        translator = self._make_translator("ko")
        originals = [{"id": "s1", "title": "EN", "summary": "EN summary"}]
        response = {
            "stories": [{"id": "s1", "title_zh": "中文标题", "summary_zh": "中文摘要"}]
        }
        with self.assertRaises(TranslationFailed) as cm:
            translator._merge(originals, response)
        self.assertIn("title_ko", str(cm.exception))
        self.assertIn("summary_ko", str(cm.exception))

    def test_merge_rejects_wrong_locale_keys_for_zh_translator(self) -> None:
        from core.translator import TranslationFailed

        translator = self._make_translator("zh")
        originals = [{"id": "s1", "title": "EN", "summary": "EN summary"}]
        response = {
            "stories": [{"id": "s1", "title_ko": "한국어", "summary_ko": "요약"}]
        }
        with self.assertRaises(TranslationFailed) as cm:
            translator._merge(originals, response)
        self.assertIn("title_zh", str(cm.exception))
        self.assertIn("summary_zh", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
