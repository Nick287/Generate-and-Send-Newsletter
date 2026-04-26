"""
Image URL validation helpers.
图片URL校验工具。
"""

from __future__ import annotations

from core.constants import BAD_IMAGE_PATTERNS, IMAGE_EXTENSIONS


def is_bad_image_url(url: str) -> bool:
    """Check if URL matches known bad/tracking image patterns."""
    if not url:
        return True
    lowered = url.lower()
    for pattern in BAD_IMAGE_PATTERNS:
        if pattern in lowered:
            return True
    return False


def url_looks_like_image(url: str) -> bool:
    """Check if URL ends with a known image extension."""
    lowered = url.lower().split("?")[0]
    return any(lowered.endswith(ext) for ext in IMAGE_EXTENSIONS)
