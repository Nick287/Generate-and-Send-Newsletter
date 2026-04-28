"""
Path constants and directory helpers for the newsletter pipeline.
新闻简报流水线的路径常量与目录工具。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# ── Directory constants | 目录常量 ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"
DATA_DIR = ROOT / "artifacts"
OUTPUT_DIR = ROOT / "dist"
TEMPLATES_DIR = ROOT / "templates"

# ── File constants | 文件常量 ───────────────────────────────────────────────
FEEDS_FILE = CONFIG_DIR / "feeds.yaml"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
# Default versions kept here for backward compatibility / single source of truth.
# 默认版本：作为向后兼容与单一真值来源。
DEFAULT_TEMPLATE_VERSION = "v7"
DEFAULT_CURATE_PROMPT_VERSION = "v5"
# Legacy constant retained for backward compatibility (curate-v5.md).
# 旧常量保留以兼容历史调用。
CURATE_PROMPT_FILE = PROMPTS_DIR / ("curate-%s.md" % DEFAULT_CURATE_PROMPT_VERSION)
TMP_HTML_FILE = Path(os.environ.get("NEWSLETTER_TMP_HTML", "/tmp/ai-newsletter.html"))
ACS_SECRET_FILE = (
    Path(os.environ.get("ACS_SECRET_FILE", ""))
    if os.environ.get("ACS_SECRET_FILE")
    else None
)

# ── Defaults | 默认值 ───────────────────────────────────────────────────────
DEFAULT_LLM_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_LLM_MODEL = "gpt-4o"
DEFAULT_ACS_SENDER = ""


# ── Path helpers | 路径工具 ─────────────────────────────────────────────────

def fetched_path(date_label: str) -> Path:
    return DATA_DIR / ("fetched-%s.json" % date_label)


def enriched_path(date_label: str) -> Path:
    return DATA_DIR / ("enriched-%s.json" % date_label)


def curated_path(date_label: str) -> Path:
    return DATA_DIR / ("curated-%s.json" % date_label)


def output_html_path(date_label: str) -> Path:
    return OUTPUT_DIR / ("newsletter-%s.html" % date_label)


# ── Version helpers | 版本工具 ─────────────────────────────────────────────
# Strict allowlist regex: only "v" + digits, e.g. v1, v7, v12. Prevents path
# traversal (e.g. "../secret") and arbitrary file reads.
# 严格白名单正则：仅允许 v+数字（如 v1/v7/v12），防止路径穿越与任意文件读取。
_VERSION_RE = re.compile(r"^v\d+$")


def _validate_version(version: str, kind: str) -> str:
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise ValueError(
            "Invalid %s version %r: must match pattern 'v<digits>' (e.g. v5, v7)"
            % (kind, version)
        )
    return version


def template_path(version: str = DEFAULT_TEMPLATE_VERSION) -> Path:
    """Return the HTML template path for the given version.
    返回指定版本的 HTML 模板路径。
    """
    safe = _validate_version(version, "template")
    return TEMPLATES_DIR / ("%s.html" % safe)


def curate_prompt_path(version: str = DEFAULT_CURATE_PROMPT_VERSION) -> Path:
    """Return the curate prompt path for the given version.
    返回指定版本的 curate prompt 路径。
    """
    safe = _validate_version(version, "curate prompt")
    return PROMPTS_DIR / ("curate-%s.md" % safe)


def ensure_directories() -> None:
    """Create data/, output/ and tmp directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_HTML_FILE.parent.mkdir(parents=True, exist_ok=True)
