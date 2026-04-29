"""Tests for template/prompt versioning helpers and defaults.
\u9a8c\u8bc1\u6a21\u677f / curate prompt \u7248\u672c\u9009\u62e9\u53ca\u9ed8\u8ba4\u503c\u3002
"""

from __future__ import annotations

import unittest

from core.paths import (
    DEFAULT_CURATE_PROMPT_VERSION,
    DEFAULT_TEMPLATE_VERSION,
    PROMPTS_DIR,
    TEMPLATES_DIR,
    curate_prompt_path,
    template_path,
)


class VersionHelpersTests(unittest.TestCase):
    def test_defaults_are_v7_and_v5(self) -> None:
        self.assertEqual(DEFAULT_TEMPLATE_VERSION, "v7")
        self.assertEqual(DEFAULT_CURATE_PROMPT_VERSION, "v5")

    def test_default_template_path_resolves_to_v7(self) -> None:
        self.assertEqual(template_path(), TEMPLATES_DIR / "v7.html")
        self.assertEqual(template_path("v7"), TEMPLATES_DIR / "v7.html")

    def test_default_curate_prompt_path_resolves_to_v5(self) -> None:
        self.assertEqual(curate_prompt_path(), PROMPTS_DIR / "curate-v5.md")
        self.assertEqual(curate_prompt_path("v5"), PROMPTS_DIR / "curate-v5.md")

    def test_template_helper_accepts_arbitrary_numeric_version(self) -> None:
        # Helper is purely path resolution; existence is checked separately
        # by ConfigLoader. Future versions like v8/v12 must work.
        self.assertEqual(template_path("v8"), TEMPLATES_DIR / "v8.html")
        self.assertEqual(template_path("v12"), TEMPLATES_DIR / "v12.html")

    def test_rejects_path_traversal(self) -> None:
        for bad in ["../secret", "v7/../x", "v", "v7a", "", "V7", "7", "v-1"]:
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    template_path(bad)
                with self.assertRaises(ValueError):
                    curate_prompt_path(bad)

    def test_rejects_non_string(self) -> None:
        for bad in [None, 7, 7.0, ["v7"]]:
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    template_path(bad)  # type: ignore[arg-type]
                with self.assertRaises(ValueError):
                    curate_prompt_path(bad)  # type: ignore[arg-type]

    def test_default_template_file_exists_in_repo(self) -> None:
        self.assertTrue(template_path().exists())
        self.assertTrue(curate_prompt_path().exists())


if __name__ == "__main__":
    unittest.main()
