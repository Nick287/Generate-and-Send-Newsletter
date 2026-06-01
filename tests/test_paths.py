"""Tests for `core.paths` helpers — version + locale validation, alias resolution.

Covers issue #28 path helper requirements:
  * `_validate_locale` rejects garbage and accepts 2-3 lowercase letters.
  * `translate_prompt_path(zh, v1)` returns the canonical path when present.
  * `translate_prompt_path(cn, v1)` resolves through the `cn ↔ zh` alias
    so legacy callers using the old code keep working after rename.
  * Unknown locales (no file on disk) still return the canonical path so the
    caller's downstream `.exists()` check raises a meaningful error.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestValidateLocale(unittest.TestCase):
    """Tests for the locale code validator."""

    def test_accepts_lowercase_two_letters(self) -> None:
        from core.paths import _validate_locale

        self.assertEqual(_validate_locale("zh"), "zh")
        self.assertEqual(_validate_locale("ko"), "ko")
        self.assertEqual(_validate_locale("ja"), "ja")
        self.assertEqual(_validate_locale("vi"), "vi")
        self.assertEqual(_validate_locale("cn"), "cn")

    def test_accepts_lowercase_three_letters(self) -> None:
        from core.paths import _validate_locale

        self.assertEqual(_validate_locale("eng"), "eng")

    def test_rejects_uppercase(self) -> None:
        from core.paths import _validate_locale

        with self.assertRaises(ValueError):
            _validate_locale("ZH")

    def test_rejects_digits(self) -> None:
        from core.paths import _validate_locale

        with self.assertRaises(ValueError):
            _validate_locale("zh1")

    def test_rejects_non_string(self) -> None:
        from core.paths import _validate_locale

        with self.assertRaises(ValueError):
            _validate_locale(None)  # type: ignore[arg-type]

    def test_rejects_empty(self) -> None:
        from core.paths import _validate_locale

        with self.assertRaises(ValueError):
            _validate_locale("")

    def test_rejects_path_traversal(self) -> None:
        from core.paths import _validate_locale

        with self.assertRaises(ValueError):
            _validate_locale("../etc")


class TestTranslatePromptPath(unittest.TestCase):
    """Tests for `translate_prompt_path` with `cn ↔ zh` alias resolution."""

    def test_zh_v1_returns_canonical_when_present(self) -> None:
        from core import paths

        with tempfile.TemporaryDirectory() as td:
            prompts_dir = Path(td)
            (prompts_dir / "translate-zh-v1.md").write_text("zh prompt", "utf-8")

            with mock.patch.object(paths, "PROMPTS_DIR", prompts_dir):
                result = paths.translate_prompt_path("zh", "v1")
                self.assertEqual(result.name, "translate-zh-v1.md")
                self.assertTrue(result.exists())

    def test_cn_falls_back_to_zh_when_canonical_missing(self) -> None:
        from core import paths

        with tempfile.TemporaryDirectory() as td:
            prompts_dir = Path(td)
            (prompts_dir / "translate-zh-v1.md").write_text("zh prompt", "utf-8")

            with mock.patch.object(paths, "PROMPTS_DIR", prompts_dir):
                result = paths.translate_prompt_path("cn", "v1")
                self.assertEqual(
                    result.name,
                    "translate-zh-v1.md",
                    "cn must alias to zh when translate-cn-v1.md missing",
                )
                self.assertTrue(result.exists())

    def test_zh_falls_back_to_cn_when_canonical_missing(self) -> None:
        from core import paths

        with tempfile.TemporaryDirectory() as td:
            prompts_dir = Path(td)
            (prompts_dir / "translate-cn-v1.md").write_text("legacy cn", "utf-8")

            with mock.patch.object(paths, "PROMPTS_DIR", prompts_dir):
                result = paths.translate_prompt_path("zh", "v1")
                self.assertEqual(
                    result.name,
                    "translate-cn-v1.md",
                    "zh must alias to legacy cn when translate-zh-v1.md missing",
                )

    def test_ko_returns_canonical_even_if_missing(self) -> None:
        from core import paths

        with tempfile.TemporaryDirectory() as td:
            prompts_dir = Path(td)
            with mock.patch.object(paths, "PROMPTS_DIR", prompts_dir):
                result = paths.translate_prompt_path("ko", "v1")
                self.assertEqual(
                    result.name,
                    "translate-ko-v1.md",
                    "Non-cn/zh locales must NOT alias; canonical path returned "
                    "so downstream .exists() check raises meaningfully.",
                )
                self.assertFalse(result.exists())

    def test_invalid_locale_raises(self) -> None:
        from core.paths import translate_prompt_path

        with self.assertRaises(ValueError):
            translate_prompt_path("XYZ", "v1")

    def test_invalid_version_raises(self) -> None:
        from core.paths import translate_prompt_path

        with self.assertRaises(ValueError):
            translate_prompt_path("zh", "badversion")


if __name__ == "__main__":
    unittest.main()
