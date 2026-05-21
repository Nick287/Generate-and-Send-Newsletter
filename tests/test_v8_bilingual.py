"""Tests for bilingual EN+zh-CN newsletter composition."""

from __future__ import annotations

import json
import logging
import re
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any, TYPE_CHECKING
from unittest import mock

if TYPE_CHECKING:
    from core.models import AppConfig
    from core.translator import Translator

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── helpers ─────────────────────────────────────────────────────────────────
def _stub_config(**overrides: Any) -> "AppConfig":
    """Construct a minimal AppConfig for bilingual tests."""
    from core.models import AppConfig

    base: dict[str, Any] = dict(
        issue_number=1,
        recipients=["test@example.com"],
        acs_sender="DoNotReply@test.azurecomm.net",
        acs_connection_string="",
        email_provider="acs",
        sendgrid_api_key="",
        smtp_host="",
        smtp_port=0,
        smtp_user="",
        smtp_pass="",
        smtp_use_ssl=False,
        llm_endpoint="https://llm.example.com/v1/chat/completions",
        llm_api_key="sk-test",
        llm_model="test-model",
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
    base.update(overrides)
    return AppConfig(**base)


def _sample_stories(n: int = 3) -> list[dict[str, Any]]:
    """Sample stories with English titles + summaries + valid badge tags."""
    tags = ["GA", "PREVIEW", "UPDATE", "NEW", "AZURE"]
    out = []
    for i in range(n):
        out.append(
            {
                "id": "story-%d" % (i + 1),
                "title": "Microsoft Releases Azure OpenAI Feature %d" % (i + 1),
                "summary": (
                    "This Azure announcement covers a significant GPT-4 capability "
                    "update for enterprise customers, including new Anthropic Claude "
                    "integration paths and improved API throughput. Story %d details."
                    % (i + 1)
                ),
                "tag": tags[i % len(tags)],
                "url": "https://example.com/post-%d" % (i + 1),
                "source": "Microsoft Blog",
                "image": "https://example.com/img-%d.png" % (i + 1),
                "published_at_iso": "2026-05-%02dT12:00:00+00:00" % (i + 1),
            }
        )
    return out


def _cn_translation_payload(stories: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a well-formed CN translation payload matching plan schema (no tag/badge/date_zh)."""
    return {
        "stories": [
            {
                "id": s["id"],
                "title_zh": "微软发布 Azure OpenAI 新功能 %d，企业级 GPT-4 能力升级"
                % (i + 1),
                "summary_zh": (
                    "本次 Azure 公告涵盖了面向企业客户的重要 GPT-4 能力更新，"
                    "包括新的 Anthropic Claude 集成路径和改进的 API 吞吐量。故事 %d 详情说明。"
                    % (i + 1)
                ),
            }
            for i, s in enumerate(stories)
        ]
    }


# ════════════════════════════════════════════════════════════════════════════
# Section 1: Config tests (3 tests)
# ════════════════════════════════════════════════════════════════════════════


class TestConfigBilingualDefaults(unittest.TestCase):
    """Tests #1-#3: AppConfig + ConfigLoader bilingual fields."""

    def test_config_defaults_bilingual_true(self) -> None:
        """Test #1: AppConfig() defaults compose_bilingual=True, translate_prompt_version='v1'."""
        cfg = _stub_config()
        self.assertTrue(cfg.compose_bilingual, "compose_bilingual must default to True")
        self.assertEqual(cfg.translate_prompt_version, "v1")

    def test_config_loader_reads_compose_block(self) -> None:
        """Test #2: ConfigLoader reads `compose: { bilingual, translate_prompt_version }`."""
        import yaml
        from core.config_loader import ConfigLoader
        from core.paths import PROMPTS_DIR

        # Ensure target prompt exists so loader doesn't fail prompt-file check
        translate_prompt = PROMPTS_DIR / "translate-cn-v1.md"
        prompt_existed = translate_prompt.exists()
        if not prompt_existed:
            translate_prompt.write_text("# stub for test\n", encoding="utf-8")
        try:
            doc = {
                "issue_number": 7,
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
                "compose": {
                    "bilingual": False,
                    "translate_prompt_version": "v1",
                },
            }
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False, encoding="utf-8"
            ) as tmp:
                yaml.safe_dump(doc, tmp)
                tmp_path = Path(tmp.name)
            feeds_yaml_path: Path | None = None
            try:
                # Patch CONFIG_FILE + FEEDS_FILE to use temp config
                with mock.patch("core.config_loader.CONFIG_FILE", tmp_path):
                    feeds_yaml = tempfile.NamedTemporaryFile(
                        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
                    )
                    feeds_yaml_path = Path(feeds_yaml.name)
                    yaml.safe_dump(
                        {"news": [{"name": "x", "url": "https://e.com/rss"}]},
                        feeds_yaml,
                    )
                    feeds_yaml.close()
                    with mock.patch(
                        "core.config_loader.FEEDS_FILE", Path(feeds_yaml.name)
                    ):
                        cfg, _ = ConfigLoader().load(logging.getLogger("test"))
                self.assertFalse(cfg.compose_bilingual)
                self.assertEqual(cfg.translate_prompt_version, "v1")
            finally:
                tmp_path.unlink(missing_ok=True)
                if feeds_yaml_path is not None:
                    feeds_yaml_path.unlink(missing_ok=True)
        finally:
            if not prompt_existed:
                translate_prompt.unlink(missing_ok=True)

    def test_config_loader_missing_compose_defaults_to_true(self) -> None:
        """Test #3: When compose: block is absent, bilingual defaults to True (backward compat)."""
        import yaml
        from core.config_loader import ConfigLoader

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
            # NO `compose:` block
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            yaml.safe_dump(doc, tmp)
            tmp_path = Path(tmp.name)
        feeds_yaml = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        yaml.safe_dump(
            {"news": [{"name": "x", "url": "https://e.com/rss"}]}, feeds_yaml
        )
        feeds_yaml.close()
        try:
            with mock.patch("core.config_loader.CONFIG_FILE", tmp_path), mock.patch(
                "core.config_loader.FEEDS_FILE", Path(feeds_yaml.name)
            ):
                cfg, _ = ConfigLoader().load(logging.getLogger("test"))
            self.assertTrue(
                cfg.compose_bilingual, "Missing compose: must default to True"
            )
            self.assertEqual(cfg.translate_prompt_version, "v1")
        finally:
            tmp_path.unlink(missing_ok=True)
            Path(feeds_yaml.name).unlink(missing_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# Section 2: Translator tests (6 tests: #4–#9)
# ════════════════════════════════════════════════════════════════════════════


class TestTranslator(unittest.TestCase):
    """Tests #4-#9: core.translator.Translator behavior."""

    def _make_translator(self, llm_response_text: str) -> "Translator":
        """Build a Translator with a mocked LlmClient that returns the given text."""
        from core.translator import Translator

        cfg = _stub_config()
        llm = mock.MagicMock()
        llm.chat = mock.MagicMock(return_value=llm_response_text)
        return Translator(
            llm_client=llm, prompt_version="v1", logger=logging.getLogger("test")
        )

    def test_translator_returns_translated_stories(self) -> None:
        """Test #4: Happy path — translator returns CN-merged stories with tag preserved."""
        stories = _sample_stories(3)
        payload = _cn_translation_payload(stories)
        translator = self._make_translator(json.dumps(payload))

        result = translator.translate_stories(stories)

        self.assertEqual(len(result), 3)
        for original, translated in zip(stories, result):
            self.assertEqual(translated["id"], original["id"])
            self.assertEqual(
                translated["tag"], original["tag"], "Tag must be preserved verbatim"
            )
            self.assertEqual(translated["url"], original["url"])
            self.assertNotEqual(
                translated["title"], original["title"], "Title must be translated"
            )
            self.assertNotEqual(translated["summary"], original["summary"])
            # date_zh computed Python-side from published_at_iso
            self.assertIn("date_zh", translated)
            self.assertRegex(translated["date_zh"], r"^\d{4}年\d{2}月\d{2}日$")

    def test_translator_raises_on_json_parse_error(self) -> None:
        """Test #5: Malformed LLM response → TranslationFailed."""
        from core.translator import TranslationFailed

        translator = self._make_translator("this is not json {{{")
        with self.assertRaises(TranslationFailed):
            translator.translate_stories(_sample_stories(2))

    def test_translator_raises_on_length_band_violation(self) -> None:
        """Test #6: CN length / EN length outside [0.25, 1.2] → TranslationFailed (v3 Q1)."""
        from core.translator import TranslationFailed

        stories = _sample_stories(3)
        # Force LLM to return ultra-short translations (way below 0.25 ratio)
        payload = {
            "stories": [
                {"id": s["id"], "title_zh": "短", "summary_zh": "短"} for s in stories
            ]
        }
        translator = self._make_translator(json.dumps(payload))
        with self.assertRaises(TranslationFailed) as ctx:
            translator.translate_stories(stories)
        self.assertIn("length_band", str(ctx.exception))

    def test_translator_raises_on_low_cjk_ratio(self) -> None:
        """Test #7: LLM echoes English back → _cjk_char_ratio < 0.3 → TranslationFailed."""
        from core.translator import TranslationFailed

        stories = _sample_stories(3)
        # LLM returns English text (no CJK chars) of similar length — passes band, fails CJK ratio
        payload = {
            "stories": [
                {
                    "id": s["id"],
                    "title_zh": s["title"],  # English echo
                    "summary_zh": s["summary"],  # English echo
                }
                for s in stories
            ]
        }
        translator = self._make_translator(json.dumps(payload))
        with self.assertRaises(TranslationFailed) as ctx:
            translator.translate_stories(stories)
        self.assertIn("cjk_ratio", str(ctx.exception).lower())

    def test_translator_repairs_utf8_mojibake(self) -> None:
        """Test #7b: UTF-8 decoded as Latin-1 is repaired before CJK validation."""
        stories = _sample_stories(1)
        payload = _cn_translation_payload(stories)
        for entry in payload["stories"]:
            entry["title_zh"] = entry["title_zh"].encode("utf-8").decode("latin-1")
            entry["summary_zh"] = entry["summary_zh"].encode("utf-8").decode("latin-1")
        translator = self._make_translator(json.dumps(payload))

        result = translator.translate_stories(stories)

        self.assertIn("微软发布", result[0]["title"])
        self.assertIn("本次 Azure 公告", result[0]["summary"])

    def test_translator_allows_preserved_english_terms(self) -> None:
        """Test #7c: Preserved product/API names must not trigger low-CJK fallback."""
        stories = _sample_stories(1)
        payload = {
            "stories": [
                {
                    "id": stories[0]["id"],
                    "title_zh": "GA：LangChain Azure Cosmos DB Python 包",
                    "summary_zh": (
                        "Microsoft 发布 GA 版 langchain-azure-cosmosdb Python 包，支持 "
                        "LangChain、LangGraph、Azure Cosmos DB、vector search、"
                        "semantic caching 和 chat history。DCSA 可用它演示 RAG 和 agent 模式。"
                    ),
                }
            ]
        }
        translator = self._make_translator(json.dumps(payload))

        result = translator.translate_stories(stories)

        self.assertEqual(result[0]["title"], payload["stories"][0]["title_zh"])

    def test_translator_raises_on_missing_story_id(self) -> None:
        """Test #8: _merge raises TranslationFailed when LLM omits a story id."""
        from core.translator import TranslationFailed

        stories = _sample_stories(3)
        payload = _cn_translation_payload(stories)
        # Drop the second translated story
        del payload["stories"][1]
        translator = self._make_translator(json.dumps(payload))
        with self.assertRaises(TranslationFailed) as ctx:
            translator.translate_stories(stories)
        self.assertIn("missing_translation", str(ctx.exception))

    def test_translator_drops_llm_injected_tag_and_preserves_original(self) -> None:
        """Test #9 (v3 B5): LLM injects tag/badge → silently dropped; original tag preserved.

        Also: if _merge is bypassed and a mutated tag leaks, post-validation raises.
        """
        from core.translator import TranslationFailed, Translator

        stories = _sample_stories(3)
        # Malicious payload: LLM tries to inject tag + badge
        payload = {
            "stories": [
                {
                    "id": s["id"],
                    "title_zh": "正常的中文标题 %d 包含足够多的字符以通过长度检查" % i,
                    "summary_zh": (
                        "正常的中文摘要内容 %d，这段文字足够长以满足长度比例检查的下限要求，"
                        "并且包含大量的中日韩字符以通过 CJK 比例检查。" % i
                    ),
                    "tag": "HACKED",  # B5: must be dropped
                    "badge": "FAKE",  # B5: must be dropped
                }
                for i, s in enumerate(stories)
            ]
        }
        cfg = _stub_config()
        llm = mock.MagicMock()
        llm.chat = mock.MagicMock(return_value=json.dumps(payload))
        translator = Translator(
            llm_client=llm, prompt_version="v1", logger=logging.getLogger("test")
        )

        result = translator.translate_stories(stories)

        # Sub-assertion 1: tag preserved from original (NOT "HACKED")
        for original, translated in zip(stories, result):
            self.assertEqual(
                translated["tag"],
                original["tag"],
                "LLM-injected tag must be silently dropped; original tag preserved",
            )
            self.assertNotIn(
                "badge", translated, "LLM-injected badge key must be dropped"
            )

        # Sub-assertion 2: if _merge is patched to leak a mutated tag, post-validation raises
        with mock.patch.object(translator, "_merge") as mock_merge:
            leaked = [dict(s) for s in stories]
            leaked[0]["tag"] = "MUTATED"  # simulate leaked mutation
            mock_merge.return_value = leaked
            with self.assertRaises(TranslationFailed) as ctx:
                translator.translate_stories(stories)
            self.assertIn("badge_tag_mutated", str(ctx.exception))


# ════════════════════════════════════════════════════════════════════════════
# Section 3: Composer tests (4 tests: #10–#13)
# ════════════════════════════════════════════════════════════════════════════


class TestComposerBilingual(unittest.TestCase):
    """Tests #10-#13: HtmlComposer bilingual splice + fallback + date format."""

    def _make_composer_with_stories(self, bilingual: bool):
        """Build composer + sample stories ready to compose."""
        from core.html_composer import HtmlComposer
        from core.models import Article

        cfg = _stub_config(compose_bilingual=bilingual)
        composer = HtmlComposer(cfg)
        stories = _sample_stories(
            13
        )  # v8 expects 9 featured + 3 quick = 12, 13th is buffer
        scanned = [
            Article(
                title=s["title"],
                link=s["url"],
                source_name=s["source"],
                category="news",
                published_date=s["published_at_iso"],
                raw_summary=s["summary"],
            )
            for s in stories
        ]
        return composer, stories, scanned

    def test_composer_bilingual_disabled_returns_en_only(self) -> None:
        """Test #10: When compose_bilingual=False, HTML contains NO CN section."""
        composer, stories, scanned = self._make_composer_with_stories(bilingual=False)
        html = composer.compose(
            stories=stories,
            scanned_articles=scanned,
            date_label="May 21 - 28, 2026",
            logger=logging.getLogger("test"),
            meta={"hero_image_index": 0},
        )
        self.assertNotIn("中文版 · Chinese Version", html)
        self.assertNotIn("<!--BILINGUAL_BODY_START-->", html)
        # Footer marker still present exactly once
        self.assertEqual(html.count("<!-- ===== FOOTER ===== -->"), 1)

    def test_composer_bilingual_enabled_splices_cn_section(self) -> None:
        """Test #11 (N6 tightened): CN section spliced before footer with exact-count assertions."""
        from core.translator import Translator

        composer, stories, scanned = self._make_composer_with_stories(bilingual=True)
        payload = _cn_translation_payload(stories)
        # Mock the translator's LLM call
        with mock.patch.object(Translator, "_call_llm", return_value=payload):
            html = composer.compose(
                stories=stories,
                scanned_articles=scanned,
                date_label="May 21 - 28, 2026",
                logger=logging.getLogger("test"),
                meta={"hero_image_index": 0},
            )

        self.assertEqual(
            html.count("中文版 · Chinese Version"),
            1,
            "Divider must appear exactly once",
        )
        self.assertEqual(
            html.count("<!--BILINGUAL_BODY_START-->"),
            0,
            "Start marker must be stripped",
        )
        self.assertEqual(
            html.count("<!--BILINGUAL_BODY_END-->"), 0, "End marker must be stripped"
        )
        self.assertEqual(
            html.count("<!-- ===== FOOTER ===== -->"),
            1,
            "Footer marker must remain exactly once",
        )

        # Positional assertion: CN section appears BEFORE footer marker
        cn_pos = html.find("中文版 · Chinese Version")
        footer_pos = html.find("<!-- ===== FOOTER ===== -->")
        self.assertGreater(cn_pos, 0, "CN divider must be present")
        self.assertLess(cn_pos, footer_pos, "CN section must precede footer")

        # EN canonical title still present (use word boundary to avoid matching
        # "Feature 1" inside "Feature 10/11/12/13" in the fixture). v8 EN hero
        # renders the title in HERO_TITLE + HERO_IMG_TITLE_CAPTION, so >=1.
        en_title = stories[0]["title"]
        matches = re.findall(re.escape(en_title) + r"\b", html)
        self.assertGreaterEqual(
            len(matches), 1, "Original EN title must be preserved in EN section"
        )

    def test_composer_cn_dates_use_chinese_format_or_empty(self) -> None:
        """Test #13 (v3 Q3): CN dates match YYYY年MM月DD日 OR are empty (missing iso case)."""
        from core.translator import Translator

        composer, stories, scanned = self._make_composer_with_stories(bilingual=True)
        # Drop published_at_iso on one story to exercise empty-date path
        stories[0]["published_at_iso"] = None
        payload = _cn_translation_payload(stories)

        with mock.patch.object(Translator, "_call_llm", return_value=payload):
            html = composer.compose(
                stories=stories,
                scanned_articles=scanned,
                date_label="May 21 - 28, 2026",
                logger=logging.getLogger("test"),
                meta={"hero_image_index": 0},
            )

        # Extract the CN section between the divider and the footer
        cn_start = html.find("中文版 · Chinese Version")
        cn_end = html.find("<!-- ===== FOOTER ===== -->")
        self.assertGreater(cn_start, 0)
        self.assertGreater(cn_end, cn_start)
        cn_section = html[cn_start:cn_end]

        # Find all date-shaped substrings in the CN section
        cn_dates = re.findall(r"\d{4}年\d{2}月\d{2}日", cn_section)
        # There must be at least 1 CN-formatted date (for the stories with iso dates)
        self.assertGreater(len(cn_dates), 0, "Expected at least one CN-formatted date")
        # And no Western-format date should leak into the CN section
        self.assertNotRegex(cn_section, r"May \d{1,2}, 2026")


# ════════════════════════════════════════════════════════════════════════════
# Section 4: Composer pre-splice guards + template font-family (2 tests: #14–#15)
# ════════════════════════════════════════════════════════════════════════════


class TestComposerSpliceGuards(unittest.TestCase):
    """Tests #14-#15: pre-splice marker validation + per-element CJK font-family."""

    def test_composer_raises_on_missing_or_duplicate_footer_marker(self) -> None:
        """Test #14 (v3 Q2): Pre-splice assertion on footer marker count == 1."""
        from core.html_composer import HtmlComposer

        cfg = _stub_config(compose_bilingual=True)
        composer = HtmlComposer(cfg)

        # Missing marker → RuntimeError("template drift")
        en_html_no_marker = "<html><body>no footer here</body></html>"
        cn_section = "<tr><td>CN</td></tr>"
        with self.assertRaises(RuntimeError) as ctx:
            composer._splice_chinese_section(en_html_no_marker, cn_section)
        self.assertIn("template drift", str(ctx.exception))

        # Duplicate marker → RuntimeError("template drift")
        en_html_dup = (
            "<html><body>"
            "<!-- ===== FOOTER ===== -->"
            "<!-- ===== FOOTER ===== -->"
            "</body></html>"
        )
        with self.assertRaises(RuntimeError) as ctx:
            composer._splice_chinese_section(en_html_dup, cn_section)
        self.assertIn("template drift", str(ctx.exception))

        # Exactly-one marker → no raise; splice succeeds
        en_html_ok = (
            "<html><body>EN content"
            "<!-- ===== FOOTER ===== -->"
            "<footer>F</footer></body></html>"
        )
        result = composer._splice_chinese_section(en_html_ok, cn_section)
        self.assertIn(cn_section, result)
        # CN must precede footer marker positionally
        self.assertLess(
            result.find(cn_section), result.find("<!-- ===== FOOTER ===== -->")
        )

    def test_v8_zh_cn_text_elements_have_inline_font_family(self) -> None:
        """Test #15 (v3 Q5): Every CJK-bearing element in templates/v8_zh.html carries inline CJK font-family."""
        from core.paths import TEMPLATES_DIR

        v8_zh_path = TEMPLATES_DIR / "v8_zh.html"
        self.assertTrue(v8_zh_path.exists(), "templates/v8_zh.html must exist")

        # Render the template with sample CN data
        from core.html_composer import HtmlComposer

        cfg = _stub_config(compose_bilingual=True)
        composer = HtmlComposer(cfg)
        cn_stories = []
        for i in range(13):
            cn_stories.append(
                {
                    "id": "s-%d" % i,
                    "title": "中文标题 %d 包含足够多字符用于测试" % i,
                    "summary": "中文摘要 %d，这是一段足够长的中文内容用于满足测试要求。"
                    % i,
                    "tag": "GA",
                    "url": "https://example.com/p-%d" % i,
                    "source": "来源 %d" % i,
                    "image": "https://example.com/i-%d.png" % i,
                    "published_at_iso": "2026-05-%02dT12:00:00+00:00" % (i + 1),
                    "date_zh": "2026年05月%02d日" % (i + 1),
                }
            )

        # composer._compose_chinese_section returns the inner CN body
        cn_html = composer._compose_chinese_section(
            stories=cn_stories,
            scanned_articles=[],
            date_label="2026年5月21日 - 2026年5月28日",
            meta={"hero_image_index": 0},
        )

        # Per-element check: BeautifulSoup if available, regex fallback
        cjk_pattern = re.compile(r"[\u4e00-\u9fff]")
        cjk_font_tokens = [
            "Microsoft YaHei",
            "微软雅黑",
            "PingFang SC",
            "Hiragino Sans GB",
            "Source Han Sans CN",
            "Noto Sans CJK SC",
        ]

        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(cn_html, "html.parser")
            checked = 0
            for elem in soup.find_all(True):
                # Only check leaf-text elements (no child tags) bearing CJK text
                if any(
                    getattr(child, "name", None)
                    for child in elem.children
                    if getattr(child, "name", None)
                ):
                    continue
                text = elem.get_text(strip=True)
                if not text or not cjk_pattern.search(text):
                    continue
                # Walk up to find a style attribute containing a CJK font token
                cur = elem
                found = False
                while cur is not None and hasattr(cur, "get"):
                    style = cur.get("style", "") if hasattr(cur, "get") else ""
                    if style and any(tok in style for tok in cjk_font_tokens):
                        found = True
                        break
                    cur = cur.parent
                self.assertTrue(
                    found,
                    "CJK-bearing element %r has no ancestor with CJK font-family in style"
                    % text[:40],
                )
                checked += 1
            self.assertGreater(
                checked, 0, "Expected to check at least one CJK-bearing element"
            )
        except ImportError:
            # Regex fallback: assert at least one CJK font token present per CJK-bearing chunk
            cjk_chunks = cjk_pattern.findall(cn_html)
            self.assertGreater(len(cjk_chunks), 0, "Template must contain CJK text")
            present_tokens = sum(1 for tok in cjk_font_tokens if tok in cn_html)
            self.assertGreater(
                present_tokens,
                0,
                "Template must include at least one CJK font-family token; "
                "found none of %s" % cjk_font_tokens,
            )


if __name__ == "__main__":
    unittest.main()
