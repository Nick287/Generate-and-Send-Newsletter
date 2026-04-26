"""
HTTP request helpers with retry.
带重试的HTTP请求工具。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests

from core.utils.logging import log_event


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    timeout: int,
    logger: logging.Logger,
    retries: int = 2,
    delay: float = 2.0,
    **kwargs: Any,
) -> requests.Response:
    """Send HTTP request with automatic retry on failure."""
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 2):
        try:
            response = session.request(
                method=method, url=url, timeout=timeout, **kwargs
            )
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            log_event(
                logger,
                logging.WARNING,
                "http_retry",
                method=method,
                url=url,
                attempt=attempt,
                error=str(exc),
            )
            if attempt <= retries:
                time.sleep(delay)
    raise RuntimeError(
        "%s %s failed after retries: %s" % (method.upper(), url, last_error)
    )
