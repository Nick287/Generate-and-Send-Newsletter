#!/usr/bin/env python3
"""
Step 0: Load Configuration — 加载配置

Input:  config.yaml, feeds.yaml, prompts/curate-v5.md
Output: Returns (AppConfig, list[FeedSource]) tuple

可独立运行，用于校验配置文件是否合法。
Can be run standalone to validate configuration files.

Usage:
    python -m steps.step0_config
    python -m steps.step0_config --date 2026-04-24
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

# ── bootstrap ────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.models import AppConfig, FeedSource
from core.paths import CURATE_PROMPT_FILE, CONFIG_FILE, FEEDS_FILE
from core.utils import (
    cleanup_old_data_files,
    ensure_directories,
    log_event,
    setup_logging,
    today_label,
)
from core.config_loader import ConfigLoader


# ── step function | 步骤函数 ─────────────────────────────────────────────────

def run(
    date_label: str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """
    Load and validate configuration.
    加载并校验配置。

    Returns dict:
        config:     AppConfig object
        feeds:      list[FeedSource]
        date_label: str
    """
    date_label = date_label or today_label()
    ensure_directories()
    logger = logger or setup_logging(date_label)

    print("=" * 60)
    print("  STEP 0 : LOAD CONFIGURATION")
    print("=" * 60)

    loader = ConfigLoader()
    config, feeds = loader.load(logger)
    cleanup_old_data_files(config.cleanup_retention_days, logger)

    print("    Config OK: %d feeds, %d recipients" % (len(feeds), len(config.recipients)))
    return {
        "config": config,
        "feeds": feeds,
        "date_label": date_label,
        "logger": logger,
    }


# ── standalone entry | 独立入口 ──────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Step 0: Validate configuration")
    parser.add_argument("--date", help="Date label (default: today)")
    args = parser.parse_args()
    try:
        result = run(date_label=args.date)
        print("\n✅ Configuration valid.")
        return 0
    except Exception as exc:
        print("\n❌ Configuration error: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
