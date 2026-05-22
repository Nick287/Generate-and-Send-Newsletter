"""Tests for the fan-out/fan-in workflow topology added in issue #28.

Covers:

  T16   build_workflow(languages=[])           -> legacy linear shape
  T17   build_workflow(languages=["zh","ko"])  -> fan-out + fan-in shape
  T18   _peek_languages() falls back to []     when config is missing/broken
  T22   --languages override semantics         (None / [] / [list])
        plus TranslateLocale failure isolation (unknown locale -> error payload)
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeCtx:
    """Minimal WorkflowContext stand-in for unit-testing executor.handle().

    Implements just enough of the ctx surface for TranslateLocale + assembler:
      * get_state / set_state (SYNC, dict-backed)
      * send_message / yield_output (async, recorded)
    """

    def __init__(self, **state: Any) -> None:
        self._state: dict[str, Any] = dict(state)
        self.sent: list[Any] = []
        self.yielded: list[Any] = []

    def get_state(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        self._state[key] = value

    async def send_message(self, msg: Any) -> None:
        self.sent.append(msg)

    async def yield_output(self, msg: Any) -> None:
        self.yielded.append(msg)


def _mermaid(workflow: Any) -> str:
    from agent_framework import WorkflowViz

    return WorkflowViz(workflow).to_mermaid()


# ════════════════════════════════════════════════════════════════════════════
# T16 — Legacy linear shape when languages is empty
# ════════════════════════════════════════════════════════════════════════════


class TestLegacyLinearTopology(unittest.TestCase):
    """T16: empty languages list keeps the legacy linear chain."""

    def test_empty_languages_produces_linear_chain(self) -> None:
        from agent_workflow import build_workflow

        wf = build_workflow(languages=[])
        mermaid = _mermaid(wf)

        self.assertIn("0-config-loader", mermaid)
        self.assertIn("1-feed-fetcher", mermaid)
        self.assertIn("2-article-enricher", mermaid)
        self.assertIn("3-story-curator", mermaid)
        self.assertIn("4-html-composer", mermaid)
        self.assertIn("5-email-sender", mermaid)
        self.assertIn(
            "n_4_html_composer --> n_5_email_sender",
            mermaid,
            "Legacy linear: HtmlComposer must connect DIRECTLY to EmailSender.",
        )

    def test_empty_languages_has_no_translate_nodes(self) -> None:
        from agent_workflow import build_workflow

        mermaid = _mermaid(build_workflow(languages=[]))
        self.assertNotIn("4b-translate", mermaid)
        self.assertNotIn("4z-locale-assembler", mermaid)
        self.assertNotIn("fan_in__", mermaid)


# ════════════════════════════════════════════════════════════════════════════
# T17 — Fan-out / fan-in shape for non-empty languages
# ════════════════════════════════════════════════════════════════════════════


class TestFanOutTopology(unittest.TestCase):
    """T17: non-empty languages produce one TranslateLocale per language."""

    def test_two_locales_create_two_translate_nodes(self) -> None:
        from agent_workflow import build_workflow

        mermaid = _mermaid(build_workflow(languages=["zh", "ko"]))

        self.assertIn("4b-translate-zh", mermaid)
        self.assertIn("4b-translate-ko", mermaid)
        self.assertIn("4z-locale-assembler", mermaid)
        self.assertIn(
            "n_4_html_composer --> n_4b_translate_zh",
            mermaid,
        )
        self.assertIn(
            "n_4_html_composer --> n_4b_translate_ko",
            mermaid,
        )

    def test_fan_in_node_present(self) -> None:
        from agent_workflow import build_workflow

        mermaid = _mermaid(build_workflow(languages=["zh", "ko"]))
        self.assertIn(
            "fan_in__",
            mermaid,
            "agent-framework must emit an explicit fan-in barrier node for "
            "list[LocaleTranslation] delivery to LocaleAssembler.",
        )

    def test_assembler_connects_to_email_sender(self) -> None:
        from agent_workflow import build_workflow

        mermaid = _mermaid(build_workflow(languages=["zh"]))
        self.assertIn("n_4z_locale_assembler --> n_5_email_sender", mermaid)

    def test_four_locales_create_four_translate_nodes(self) -> None:
        from agent_workflow import build_workflow

        mermaid = _mermaid(build_workflow(languages=["zh", "ja", "ko", "vi"]))
        for locale in ("zh", "ja", "ko", "vi"):
            self.assertIn(
                "4b-translate-%s" % locale,
                mermaid,
                "Locale %r missing from fan-out topology" % locale,
            )

    def test_html_composer_never_connects_directly_to_email_sender_in_fan_out(
        self,
    ) -> None:
        """Smoke guard: fan-out branch must route THROUGH LocaleAssembler."""
        from agent_workflow import build_workflow

        mermaid = _mermaid(build_workflow(languages=["zh"]))
        self.assertNotIn(
            "n_4_html_composer --> n_5_email_sender",
            mermaid,
            "Fan-out topology must NOT keep the legacy direct edge.",
        )


# ════════════════════════════════════════════════════════════════════════════
# T18 — _peek_languages defensive fallback
# ════════════════════════════════════════════════════════════════════════════


class TestPeekLanguagesFallback(unittest.TestCase):
    """T18: _peek_languages must NEVER raise during module import."""

    def test_peek_languages_returns_empty_on_step0_failure(self) -> None:
        import agent_workflow

        with mock.patch.object(
            agent_workflow, "_step0_config", side_effect=RuntimeError("config missing")
        ):
            self.assertEqual(agent_workflow._peek_languages(), [])

    def test_peek_languages_returns_config_value_on_success(self) -> None:
        import agent_workflow

        class _Cfg:
            compose_languages = ["zh", "ja"]

        with mock.patch.object(
            agent_workflow, "_step0_config", return_value={"config": _Cfg()}
        ):
            self.assertEqual(agent_workflow._peek_languages(), ["zh", "ja"])

    def test_peek_languages_handles_missing_attribute(self) -> None:
        import agent_workflow

        class _Cfg:
            pass  # no compose_languages attr

        with mock.patch.object(
            agent_workflow, "_step0_config", return_value={"config": _Cfg()}
        ):
            self.assertEqual(agent_workflow._peek_languages(), [])

    def test_build_workflow_falls_back_to_peek_when_languages_none(self) -> None:
        import agent_workflow

        class _Cfg:
            compose_languages = ["zh"]

        with mock.patch.object(
            agent_workflow, "_step0_config", return_value={"config": _Cfg()}
        ):
            wf = agent_workflow.build_workflow(languages=None)
            mermaid = _mermaid(wf)
            self.assertIn("4b-translate-zh", mermaid)


# ════════════════════════════════════════════════════════════════════════════
# T22 — WorkflowInput field + TranslateLocale failure isolation
# ════════════════════════════════════════════════════════════════════════════


class TestWorkflowInputLanguagesField(unittest.TestCase):
    """T22: WorkflowInput.languages: list[str] | None field exists with default."""

    def test_default_is_none(self) -> None:
        from agent_workflow import WorkflowInput

        wf_in = WorkflowInput()
        self.assertIsNone(wf_in.languages)

    def test_accepts_empty_list(self) -> None:
        from agent_workflow import WorkflowInput

        wf_in = WorkflowInput(languages=[])
        self.assertEqual(wf_in.languages, [])

    def test_accepts_locale_list(self) -> None:
        from agent_workflow import WorkflowInput

        wf_in = WorkflowInput(languages=["zh", "ko"])
        self.assertEqual(wf_in.languages, ["zh", "ko"])


class TestTranslateLocaleFailureIsolation(unittest.TestCase):
    """T22: a single locale's failure must NEVER raise — produces error payload."""

    def test_unknown_locale_emits_error_payload(self) -> None:
        from agent_workflow import (
            SS_CONFIG,
            SS_STORIES,
            LocaleTranslation,
            TranslateLocale,
            TranslateTrigger,
        )

        executor = TranslateLocale("xx")  # not in LocaleConfig
        ctx = _FakeCtx(**{SS_CONFIG: object(), SS_STORIES: []})

        asyncio.run(executor.handle(TranslateTrigger(), ctx))  # type: ignore[arg-type]

        self.assertEqual(len(ctx.sent), 1)
        msg = ctx.sent[0]
        self.assertIsInstance(msg, LocaleTranslation)
        self.assertEqual(msg.locale, "xx")
        self.assertEqual(msg.status, "error")
        self.assertIn("unknown locale", (msg.error or "").lower())
        self.assertEqual(msg.stories, [])

    def test_translator_exception_emits_error_payload(self) -> None:
        """A failing Translator must produce LocaleTranslation(status='error'),
        NOT propagate the exception (otherwise the whole workflow aborts)."""
        from agent_workflow import (
            SS_CONFIG,
            SS_STORIES,
            LocaleTranslation,
            TranslateLocale,
            TranslateTrigger,
        )

        executor = TranslateLocale("zh")
        ctx = _FakeCtx(**{SS_CONFIG: mock.MagicMock(), SS_STORIES: [{"id": "s1"}]})

        with mock.patch("core.llm_client.LlmClient"):
            failing_translator = mock.MagicMock()
            failing_translator.translate_stories.side_effect = RuntimeError(
                "LLM exploded"
            )
            with mock.patch(
                "core.translator.Translator", return_value=failing_translator
            ):
                asyncio.run(executor.handle(TranslateTrigger(), ctx))  # type: ignore[arg-type]

        self.assertEqual(len(ctx.sent), 1)
        msg = ctx.sent[0]
        self.assertIsInstance(msg, LocaleTranslation)
        self.assertEqual(msg.locale, "zh")
        self.assertEqual(msg.status, "error")
        self.assertIn("LLM exploded", msg.error or "")

    def test_cancellation_propagates(self) -> None:
        """asyncio.CancelledError must NOT be caught — cooperative cancellation."""
        from agent_workflow import (
            SS_CONFIG,
            SS_STORIES,
            TranslateLocale,
            TranslateTrigger,
        )

        executor = TranslateLocale("zh")
        ctx = _FakeCtx(**{SS_CONFIG: mock.MagicMock(), SS_STORIES: [{"id": "s1"}]})

        with mock.patch("core.llm_client.LlmClient"):
            cancelling = mock.MagicMock()
            cancelling.translate_stories.side_effect = asyncio.CancelledError()
            with mock.patch("core.translator.Translator", return_value=cancelling):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(executor.handle(TranslateTrigger(), ctx))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
