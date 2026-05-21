"""Translator — translates curated EN newsletter stories into Simplified Chinese."""

from __future__ import annotations

import datetime
import json
import logging
import re
from typing import Any

from core.llm_client import LlmClient
from core.paths import translate_prompt_path

_LENGTH_BAND_MIN = 0.25
_LENGTH_BAND_MAX = 1.2
_MIN_CJK_RATIO = 0.3
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class TranslationFailed(RuntimeError):
    """Raised when the LLM translation cannot be trusted (parse / length / CJK / id / mutation)."""


class Translator:
    """Translates curated newsletter stories from English to Simplified Chinese.

    Wire-up:
      result = Translator(llm_client, prompt_version, logger).translate_stories(stories)

    `result` is a deep-copied list of stories with `title`/`summary` replaced by the
    Chinese translation and a new `date_zh` field added. The original `tag`, `url`,
    `source`, `image`, and `id` fields are preserved verbatim — the LLM is not
    permitted to mutate them.
    """

    def __init__(
        self,
        llm_client: LlmClient,
        prompt_version: str,
        logger: logging.Logger,
    ) -> None:
        self._llm = llm_client
        self._prompt_version = prompt_version
        self._logger = logger

    def translate_stories(self, stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not stories:
            return []

        parsed = self._call_llm(stories)
        merged = self._merge(stories, parsed)

        self._validate_tags_unchanged(stories, merged)
        self._validate_lengths(stories, merged)
        self._validate_cjk(merged)

        for translated, original in zip(merged, stories):
            translated["date_zh"] = self._format_date_zh(
                original.get("published_at_iso") or original.get("published_date")
            )

        return merged

    def _call_llm(self, stories: list[dict[str, Any]]) -> dict[str, Any]:
        prompt_path = translate_prompt_path(self._prompt_version)
        template = prompt_path.read_text(encoding="utf-8")
        stories_for_llm = [
            {
                "id": self._story_id(s, idx),
                "title": s.get("title", ""),
                "summary": s.get("summary", ""),
            }
            for idx, s in enumerate(stories)
        ]
        user_prompt = template.replace(
            "{{STORIES_JSON}}",
            json.dumps(stories_for_llm, ensure_ascii=False, indent=2),
        )
        try:
            raw = self._llm.chat(
                system_prompt="You are a professional bilingual technical translator.",
                user_prompt=user_prompt,
                retries=1,
                delay_seconds=8.0,
            )
        except Exception as exc:
            raise TranslationFailed("llm_call_error: %s" % exc) from exc
        try:
            return LlmClient.parse_json_value(raw)
        except Exception as exc:
            raise TranslationFailed("json_parse_error: %s" % exc) from exc

    def _merge(
        self,
        original_stories: list[dict[str, Any]],
        llm_response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not isinstance(llm_response, dict):
            raise TranslationFailed("json_parse_error: response not a JSON object")
        cn_entries = llm_response.get("stories")
        if not isinstance(cn_entries, list):
            raise TranslationFailed(
                "json_parse_error: stories field missing or not a list"
            )

        by_id: dict[str, dict[str, Any]] = {}
        for entry in cn_entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            if not isinstance(entry_id, str):
                continue
            entry.pop("tag", None)
            entry.pop("badge", None)
            by_id[entry_id] = entry

        merged: list[dict[str, Any]] = []
        for idx, original in enumerate(original_stories):
            sid = self._story_id(original, idx)
            if sid not in by_id:
                raise TranslationFailed("missing_translation id=%r" % sid)
            cn = by_id[sid]
            title_zh = cn.get("title_zh")
            summary_zh = cn.get("summary_zh")
            if not isinstance(title_zh, str) or not isinstance(summary_zh, str):
                raise TranslationFailed(
                    "missing_translation id=%r (title_zh/summary_zh)" % sid
                )
            out = dict(original)
            out["title"] = self._repair_utf8_mojibake(title_zh)
            out["summary"] = self._repair_utf8_mojibake(summary_zh)
            merged.append(out)
        return merged

    def _validate_lengths(
        self,
        originals: list[dict[str, Any]],
        merged: list[dict[str, Any]],
    ) -> None:
        for original, translated in zip(originals, merged):
            en_text = self._combined_text(original)
            cn_text = self._combined_text(translated)
            en_len = max(len(en_text), 1)
            ratio = len(cn_text) / en_len
            if ratio < _LENGTH_BAND_MIN or ratio > _LENGTH_BAND_MAX:
                raise TranslationFailed(
                    "length_band violation id=%r ratio=%.3f (allowed %.2f-%.2f)"
                    % (original.get("id"), ratio, _LENGTH_BAND_MIN, _LENGTH_BAND_MAX)
                )

    def _validate_cjk(self, merged: list[dict[str, Any]]) -> None:
        for translated in merged:
            cn_text = self._combined_text(translated)
            ratio = self._cjk_char_ratio(cn_text)
            if ratio < _MIN_CJK_RATIO:
                raise TranslationFailed(
                    "cjk_ratio too low id=%r ratio=%.3f (minimum %.2f)"
                    % (translated.get("id"), ratio, _MIN_CJK_RATIO)
                )

    @staticmethod
    def _repair_utf8_mojibake(text: str) -> str:
        if not text or _CJK_RE.search(text):
            return text
        try:
            repaired = text.encode("latin-1").decode("utf-8")
        except UnicodeError:
            return text
        return repaired if _CJK_RE.search(repaired) else text

    @staticmethod
    def _story_id(story: dict[str, Any], index: int) -> str:
        sid = story.get("id")
        if isinstance(sid, str) and sid.strip():
            return sid
        link = story.get("link") or story.get("url")
        if isinstance(link, str) and link.strip():
            return link
        return "story-%d" % (index + 1)

    @staticmethod
    def _validate_tags_unchanged(
        originals: list[dict[str, Any]],
        merged: list[dict[str, Any]],
    ) -> None:
        for original, translated in zip(originals, merged):
            if translated.get("tag") != original.get("tag"):
                raise TranslationFailed(
                    "badge_tag_mutated id=%r original=%r leaked=%r"
                    % (original.get("id"), original.get("tag"), translated.get("tag"))
                )
            if "badge" in translated and translated["badge"] != original.get("badge"):
                raise TranslationFailed(
                    "badge_tag_mutated id=%r badge leaked" % original.get("id")
                )

    @staticmethod
    def _combined_text(story: dict[str, Any]) -> str:
        title = story.get("title", "") or ""
        summary = story.get("summary", "") or ""
        return "%s %s" % (title, summary)

    @staticmethod
    def _cjk_char_ratio(text: str) -> float:
        normalized = re.sub(r"[A-Za-z0-9_./:+#-]+", "", text or "")
        normalized = re.sub(r"\s+", "", normalized)
        if not normalized:
            return 0.0
        cjk = len(_CJK_RE.findall(normalized))
        return cjk / len(normalized)

    @staticmethod
    def _format_date_zh(iso_str: Any) -> str:
        if not isinstance(iso_str, str) or not iso_str.strip():
            return ""
        try:
            value = iso_str.strip()
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt = datetime.datetime.fromisoformat(value)
            return dt.strftime("%Y年%m月%d日")
        except (ValueError, TypeError):
            return ""
