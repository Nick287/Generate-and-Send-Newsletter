"""
Logging setup, structured event logging, and notifications.
日志初始化、结构化事件日志与通知。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.paths import DATA_DIR


def setup_logging(date_label: str) -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ai-newsletter-v5")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(message)s")
    file_handler = logging.FileHandler(
        DATA_DIR / ("run-%s.log" % date_label), encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Emit a structured JSON log event with timestamp."""
    payload = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "level": logging.getLevelName(level),
        "event": event,
    }
    payload.update(fields)
    logger.log(level, json.dumps(payload, ensure_ascii=False, sort_keys=True))


def tg(msg: str) -> None:
    """Send a progress notification via external script (e.g. Telegram bot)."""
    script_path = os.environ.get("TG_NOTIFY_SCRIPT", "")
    if not script_path:
        return
    script = Path(script_path)
    if not script.exists():
        return
    try:
        subprocess.run([str(script), msg], timeout=15, capture_output=True)
    except Exception:
        pass
