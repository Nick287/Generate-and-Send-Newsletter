"""
Tests for v8 template rendering and curator object-shape parsing.
v8 模板渲染与 curator 对象输出解析的测试。
"""

from __future__ import annotations

import json
import logging
import re
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.html_composer import HtmlComposer  # noqa: E402
from core.content_curator import ContentCurator  # noqa: E402
from core.models import AppConfig, Article  # noqa: E402


def _stub_config(template_version: str = "v8") -> AppConfig:
    return AppConfig(
        issue_number=99,
        recipients=["a@b.com"],
        acs_sender="",
        acs_connection_string="",
        email_provider="acs",
        sendgrid_api_key="",
        smtp_host="",
        smtp_port=0,
        smtp_user="",
        smtp_pass="",
        smtp_use_ssl=False,
        llm_endpoint="",
        llm_api_key="",
        llm_model="",
        llm_temperature=0.2,
        llm_max_tokens=8000,
        llm_timeout=180,
        fetch_window_days=7,
        fetch_max_workers=10,
        fetch_max_per_feed=25,
        arxiv_cap_per_category=10,
        fetch_fail_threshold=0.5,
        enrich_top_candidates=40,
        enrich_fetch_delay=0.5,
        enrich_fetch_timeout=15,
        enrich_max_body_chars=3000,
        cleanup_retention_days=30,
        template_version=template_version,
        curate_prompt_version="v8" if template_version == "v8" else "v5",
    )


def _sample_stories(n: int = 8) -> list[dict]:
    out = []
    tags = [
        "PLATFORM",
        "INDUSTRY",
        "TOOLS",
        "ANALYSIS",
        "LAUNCH",
        "RESEARCH",
        "QUICK",
        "AZURE",
    ]
    for i in range(n):
        out.append(
            {
                "title": f"Story {i+1} title",
                "link": f"https://example.com/post-{i+1}",
                "source": f"Source {i+1}",
                "summary": f"Summary {i+1}.",
                "oneliner": f"Oneliner {i+1}.",
                "score": 20 - i,
                "read_time_minutes": 3 + (i % 4),
                "image_url": (
                    f"https://example.com/img-{i+1}.jpg" if i % 2 == 0 else None
                ),
                "tag": tags[i % len(tags)],
                "published_date": "2026-04-25T12:00:00Z",
            }
        )
    return out


def _azure_article(
    title: str = "Generally available: Azure AI service update",
) -> Article:
    return Article(
        title=title,
        link="https://azure.microsoft.com/updates/example",
        source_name="Azure Updates Feed",
        category="azure_microsoft",
        published_date="2026-04-25T12:00:00Z",
        raw_summary="Azure update details.",
    )


class V8RenderTests(unittest.TestCase):
    def test_v8_render_no_unresolved_placeholders(self) -> None:
        config = _stub_config("v8")
        composer = HtmlComposer(config)
        stories = _sample_stories(8)
        meta = {
            "headline": "Big AI things happened",
            "tldr": "This week AI digest TLDR.",
            "hero_image_index": 0,
        }
        html = composer.compose(stories, [], "Apr 21 – Apr 27, 2026", meta=meta)
        unresolved = re.findall(r"\{\{[A-Z0-9_]+\}\}", html)
        self.assertEqual(unresolved, [], f"unresolved placeholders: {unresolved[:5]}")
        self.assertIn("Big AI things happened", html)
        self.assertIn("This week AI digest TLDR.", html)

    def test_v7_default_still_renders(self) -> None:
        config = _stub_config("v7")
        composer = HtmlComposer(config)
        html = composer.compose(_sample_stories(8), [], "Apr 21 – Apr 27, 2026")
        unresolved = re.findall(r"\{\{[A-Z0-9_]+\}\}", html)
        self.assertEqual(
            unresolved, [], f"v7 unresolved placeholders: {unresolved[:5]}"
        )

    def test_v8_falls_back_to_first_story_when_meta_empty(self) -> None:
        config = _stub_config("v8")
        composer = HtmlComposer(config)
        stories = _sample_stories(7)
        html = composer.compose(stories, [], "Apr 21 – Apr 27, 2026", meta={})
        unresolved = re.findall(r"\{\{[A-Z0-9_]+\}\}", html)
        self.assertEqual(unresolved, [])
        self.assertIn("Story 1 title", html)

    def test_v8_hides_azure_sidebar_when_no_azure_items(self) -> None:
        config = _stub_config("v8")
        composer = HtmlComposer(config)
        html = composer.compose(
            _sample_stories(8), [], "Apr 21 – Apr 27, 2026", meta={}
        )
        self.assertNotIn("Azure Updates", html)

    def test_v8_renders_azure_sidebar_when_items_exist(self) -> None:
        config = _stub_config("v8")
        composer = HtmlComposer(config)
        html = composer.compose(
            _sample_stories(8),
            [_azure_article()],
            "Apr 21 – Apr 27, 2026",
            meta={},
        )
        self.assertIn("Azure Updates", html)
        self.assertIn("Azure AI service update", html)
        self.assertIn("GA", html)


class V8NineCardsTests(unittest.TestCase):
    """Lock the v8 layout contract: 1 hero + 9 featured cards + 3 quick reads."""

    def test_v8_template_exposes_nine_card_placeholders(self) -> None:
        """templates/v8.html must declare C1..C9 placeholders (one TITLE per card)."""
        template_path = ROOT / "templates" / "v8.html"
        raw = template_path.read_text(encoding="utf-8")
        for i in range(1, 10):
            self.assertIn(f"{{{{C{i}_TITLE}}}}", raw, f"missing C{i}_TITLE placeholder")
            self.assertIn(f"{{{{C{i}_LINK}}}}", raw, f"missing C{i}_LINK placeholder")
            self.assertIn(f"{{{{C{i}_IMAGE}}}}", raw, f"missing C{i}_IMAGE placeholder")

    def test_v8_renders_nine_cards_when_thirteen_stories(self) -> None:
        """With 13 stories (1 hero + 9 cards + 3 QR), all 9 card titles appear."""
        config = _stub_config("v8")
        composer = HtmlComposer(config)
        stories = _sample_stories(13)
        meta = {"headline": "H", "tldr": "T", "hero_image_index": 0}
        html = composer.compose(stories, [], "Apr 21 – Apr 27, 2026", meta=meta)
        # hero is stories[0]; cards draw from stories[1..9]; QR from stories[10..12]
        for i in range(2, 11):  # Story 2..Story 10
            self.assertIn(f"Story {i} title", html, f"card slot {i-1} not rendered")
        for i in range(11, 14):  # Story 11..Story 13 in QR
            self.assertIn(f"Story {i} title", html, f"QR slot {i-10} not rendered")
        unresolved = re.findall(r"\{\{[A-Z0-9_]+\}\}", html)
        self.assertEqual(unresolved, [], f"unresolved placeholders: {unresolved[:5]}")

    def test_v8_nine_cards_with_short_input_leaves_empty_slots_clean(self) -> None:
        """With only 8 stories, surplus card slots render with empty title/no '#' leak in title."""
        config = _stub_config("v8")
        composer = HtmlComposer(config)
        stories = _sample_stories(8)
        meta = {"headline": "H", "tldr": "T", "hero_image_index": 0}
        html = composer.compose(stories, [], "Apr 21 – Apr 27, 2026", meta=meta)
        # No unresolved placeholders even when stories < 13.
        unresolved = re.findall(r"\{\{[A-Z0-9_]+\}\}", html)
        self.assertEqual(unresolved, [], f"unresolved placeholders: {unresolved[:5]}")
        # First 7 stories after hero populate C1..C7; C8/C9 empty.
        for i in range(2, 9):  # Story 2..Story 8
            self.assertIn(f"Story {i} title", html)


class V8CuratorParseTests(unittest.TestCase):
    def test_v8_object_payload_normalized(self) -> None:
        config = _stub_config("v8")
        logger = logging.getLogger("test")
        curator = ContentCurator(config, logger)
        payload = {
            "headline": "Headline X",
            "tldr": "TLDR Y.",
            "hero_image_index": 1,
            "stories": [
                {
                    "title": "T1",
                    "link": "https://e.com/1",
                    "source": "S",
                    "summary": "Sum",
                    "oneliner": "1",
                    "score": 20,
                    "read_time_minutes": 3,
                    "image_url": None,
                    "tag": "PLATFORM",
                    "published_date": "2026-04-25T00:00:00Z",
                }
            ],
        }
        stories, meta = curator._normalize_payload(payload)
        self.assertEqual(meta["headline"], "Headline X")
        self.assertEqual(meta["tldr"], "TLDR Y.")
        self.assertEqual(meta["hero_image_index"], 1)
        self.assertEqual(len(stories), 1)

    def test_v5_array_payload_yields_empty_meta(self) -> None:
        config = _stub_config("v8")
        logger = logging.getLogger("test")
        curator = ContentCurator(config, logger)
        payload = [
            {
                "title": "T1",
                "link": "https://e.com/1",
                "source": "S",
                "summary": "Sum",
                "oneliner": "1",
                "score": 20,
                "read_time_minutes": 3,
                "image_url": None,
                "tag": "RESEARCH",
            }
        ]
        stories, meta = curator._normalize_payload(payload)
        self.assertEqual(meta, {})
        self.assertEqual(len(stories), 1)


class SubjectFormatTests(unittest.TestCase):
    """Ensure email subject is professional: no emoji, no 'v8', no Issue marker."""

    def _build_subject(self, window_days: int = 7) -> str:
        from core.utils import week_range_label

        return "AI Weekly Digest — Week of %s" % (
            week_range_label(window_days=window_days),
        )

    def test_no_emoji(self) -> None:
        subj = self._build_subject()
        emoji_pattern = re.compile(
            "["
            "\U0001f600-\U0001f64f"
            "\U0001f300-\U0001f5ff"
            "\U0001f680-\U0001f6ff"
            "\U0001f1e0-\U0001f1ff"
            "\U00002702-\U000027b0"
            "\U0001f900-\U0001f9ff"
            "]+",
            flags=re.UNICODE,
        )
        self.assertIsNone(emoji_pattern.search(subj), f"Subject contains emoji: {subj}")

    def test_no_v8(self) -> None:
        subj = self._build_subject()
        self.assertNotIn("v8", subj.lower(), f"Subject contains 'v8': {subj}")

    def test_no_issue_marker(self) -> None:
        subj = self._build_subject()
        self.assertNotRegex(
            subj, r"(?i)issue", f"Subject contains Issue marker: {subj}"
        )
        self.assertNotRegex(subj, r"\[.*#.*\]", f"Subject contains [#N] marker: {subj}")


if __name__ == "__main__":
    unittest.main()
