"""
Constants used across the newsletter pipeline.
新闻简报流水线中使用的常量。

Includes: image filters, regex patterns, tag definitions, placeholder colors.
包含：图片过滤规则、正则表达式、标签定义、占位符颜色。
"""

from __future__ import annotations

import re

# ── Image filtering | 图片过滤 ──────────────────────────────────────────────
BAD_IMAGE_PATTERNS = [
    "arxiv.org/icons",
    "static.arxiv.org",
    "gravatar.com",
    "wp-content/uploads/avatar",
    "s.w.org",
    "feeds.feedburner.com",
    "pixel",
    "track",
    "1x1",
    "spacer",
    "icon",
    "opengraph.githubassets.com",
    "repository-images.githubusercontent.com",
    "avatars.githubusercontent.com",
]

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# ── GitHub release version filtering | GitHub 版本过滤 ──────────────────────
SEMVER_PATTERN = re.compile(r"^v?\d+\.\d+(\.\d+)?(-[\w.]+)?$")
_BUILD_NUMBER_PATTERN = re.compile(r"^b\d+$")
_HEX_HASH_PATTERN = re.compile(r"^[a-f0-9]{7,}$")
_PRERELEASE_PATTERN = re.compile(r"(rc\d*|alpha|beta|preview|nightly|dev)", re.IGNORECASE)

# ── Newsletter tags | 新闻简报标签 ──────────────────────────────────────────
# ── Newsletter tags | 新闻简报标签 ──────────────────────────────────────────
# Union of v5 (uppercase) and v8 (mixed-case) editorial tag sets. After
# uppercase normalization in _sanitize_story we accept both vocabularies.
# v5 与 v8 编辑标签合集；_sanitize_story 会先转大写再校验。
VALID_TAGS = {
    # v5 vocabulary
    "HEADLINE", "RESEARCH", "TOOL", "AZURE", "QUICK",
    # v8 vocabulary (uppercased)
    "PLATFORM", "INDUSTRY", "TOOLS", "ANALYSIS", "LAUNCH",
}

TAG_PLACEHOLDER_COLORS = {
    "HEADLINE": "0078D4",
    "RESEARCH": "5E6AD2",
    "TOOL": "059669",
    "TOOLS": "059669",
    "AZURE": "0078D4",
    "QUICK": "6B7280",
    "PLATFORM": "0078D4",
    "INDUSTRY": "D97706",
    "ANALYSIS": "7C3AED",
    "LAUNCH": "DC2626",
}
