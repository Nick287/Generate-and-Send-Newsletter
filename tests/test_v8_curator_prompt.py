"""Tests for v8 curator prompt shape."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.content_curator import ContentCurator  # noqa: E402
from core.models import AppConfig, Article  # noqa: E402


def _stub_config() -> AppConfig:
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
        template_version="v8",
        curate_prompt_version="v8",
    )


class V8CuratorPromptTests(unittest.TestCase):
    def test_v8_user_prompt_requests_object_payload(self) -> None:
        curator = ContentCurator(_stub_config(), logging.getLogger("test"))
        captured: dict[str, str] = {}

        def fake_chat(system_prompt: str, user_prompt: str, **kwargs: object) -> str:
            captured["user_prompt"] = user_prompt
            return json.dumps({
                "headline": "Headline X",
                "tldr": "TLDR Y.",
                "hero_image_index": 0,
                "stories": [{
                    "title": "Article 1",
                    "link": "https://example.com/article-1",
                    "source": "Source 1",
                    "summary": "Summary 1",
                    "oneliner": "Oneliner 1",
                    "score": 20,
                    "read_time_minutes": 3,
                    "image_url": None,
                    "tag": "Platform",
                    "published_date": "2026-04-25T12:00:00Z",
                }],
            })

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "curated-2099-01-01.json"
            with mock.patch.object(curator.llm, "chat", side_effect=fake_chat), \
                    mock.patch("core.content_curator.curated_path", return_value=out_path):
                curator.curate([
                    Article(
                        title="Article 1",
                        link="https://example.com/article-1",
                        source_name="Source 1",
                        category="azure_microsoft",
                        published_date="2026-04-25T12:00:00Z",
                        raw_summary="Summary 1",
                    )
                ], "2099-01-01")

        self.assertIn("required JSON object", captured["user_prompt"])
        self.assertNotIn("flat JSON array", captured["user_prompt"])


if __name__ == "__main__":
    unittest.main()
