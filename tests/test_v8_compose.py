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
    tags = ["PLATFORM", "INDUSTRY", "TOOLS", "ANALYSIS", "LAUNCH", "RESEARCH", "QUICK", "AZURE"]
    for i in range(n):
        out.append({
            "title": f"Story {i+1} title",
            "link": f"https://example.com/post-{i+1}",
            "source": f"Source {i+1}",
            "summary": f"Summary {i+1}.",
            "oneliner": f"Oneliner {i+1}.",
            "score": 20 - i,
            "read_time_minutes": 3 + (i % 4),
            "image_url": f"https://example.com/img-{i+1}.jpg" if i % 2 == 0 else None,
            "tag": tags[i % len(tags)],
            "published_date": "2026-04-25T12:00:00Z",
        })
    return out


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
        self.assertEqual(unresolved, [], f"v7 unresolved placeholders: {unresolved[:5]}")

    def test_v8_falls_back_to_first_story_when_meta_empty(self) -> None:
        config = _stub_config("v8")
        composer = HtmlComposer(config)
        stories = _sample_stories(7)
        html = composer.compose(stories, [], "Apr 21 – Apr 27, 2026", meta={})
        unresolved = re.findall(r"\{\{[A-Z0-9_]+\}\}", html)
        self.assertEqual(unresolved, [])
        self.assertIn("Story 1 title", html)


class V8CuratorParseTests(unittest.TestCase):
    def test_v8_object_payload_normalized(self) -> None:
        config = _stub_config("v8")
        logger = logging.getLogger("test")
        curator = ContentCurator(config, logger)
        payload = {
            "headline": "Headline X",
            "tldr": "TLDR Y.",
            "hero_image_index": 1,
            "stories": [{
                "title": "T1", "link": "https://e.com/1", "source": "S",
                "summary": "Sum", "oneliner": "1", "score": 20,
                "read_time_minutes": 3, "image_url": None, "tag": "PLATFORM",
                "published_date": "2026-04-25T00:00:00Z",
            }],
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
        payload = [{
            "title": "T1", "link": "https://e.com/1", "source": "S",
            "summary": "Sum", "oneliner": "1", "score": 20,
            "read_time_minutes": 3, "image_url": None, "tag": "RESEARCH",
        }]
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
            "[" "\U0001F600-\U0001F64F" "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF" "\U0001F1E0-\U0001F1FF"
            "\U00002702-\U000027B0" "\U0001F900-\U0001F9FF" "]+",
            flags=re.UNICODE,
        )
        self.assertIsNone(emoji_pattern.search(subj), f"Subject contains emoji: {subj}")

    def test_no_v8(self) -> None:
        subj = self._build_subject()
        self.assertNotIn("v8", subj.lower(), f"Subject contains 'v8': {subj}")

    def test_no_issue_marker(self) -> None:
        subj = self._build_subject()
        self.assertNotRegex(subj, r"(?i)issue", f"Subject contains Issue marker: {subj}")
        self.assertNotRegex(subj, r"\[.*#.*\]", f"Subject contains [#N] marker: {subj}")


if __name__ == "__main__":
    unittest.main()
