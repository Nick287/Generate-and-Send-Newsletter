"""
Path constants and directory helpers for the newsletter pipeline.
新闻简报流水线的路径常量与目录工具。
"""

from __future__ import annotations

import os
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
CURATE_PROMPT_FILE = PROMPTS_DIR / "curate-v5.md"
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


def ensure_directories() -> None:
    """Create data/, output/ and tmp directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_HTML_FILE.parent.mkdir(parents=True, exist_ok=True)
