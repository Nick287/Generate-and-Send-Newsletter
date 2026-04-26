"""
Data file cleanup utility.
数据文件清理工具。
"""

from __future__ import annotations

import datetime as dt
import logging

from core.paths import DATA_DIR
from core.utils.dates import utc_now
from core.utils.logging import log_event


def cleanup_old_data_files(retention_days: int, logger: logging.Logger) -> None:
    """Delete data files older than retention_days."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = utc_now() - dt.timedelta(days=retention_days)
    deleted: list[str] = []
    for path in DATA_DIR.iterdir():
        if not path.is_file():
            continue
        try:
            modified = dt.datetime.fromtimestamp(
                path.stat().st_mtime, tz=dt.timezone.utc
            )
            if modified < cutoff:
                path.unlink()
                deleted.append(path.name)
        except Exception as exc:
            log_event(
                logger, logging.WARNING, "cleanup_error", file=path.name, error=str(exc)
            )
    log_event(
        logger,
        logging.INFO,
        "cleanup_complete",
        deleted_files=deleted,
        retention_days=retention_days,
    )
