"""
Redaction helpers for sensitive PII (e.g. recipient email addresses).
敏感信息 (如收件人邮箱) 的脱敏工具。

These helpers are used by the email dispatcher and any logging surface that
would otherwise print or persist raw email recipients to stdout, run logs,
or artifacts (send-log.json). They preserve enough information for debugging
(first character of local-part and domain, original length category) without
disclosing the full address.
"""

from __future__ import annotations

from typing import Iterable


def mask_email(value: str) -> str:
    """Return a masked form of an email-like string.

    Rules:
      - Non-string / empty input -> "" (empty string).
      - Strings without an "@" or with empty local/domain parts are masked
        as "***" (treated as opaque).
      - Otherwise mask local-part and domain-name with first char + "***",
        keeping the TLD visible for routing diagnostics:
          "alice@example.com" -> "a***@e***.com"
          "ab@x.io"            -> "a***@x***.io"
      - Domains without a dot keep just first char + "***".
    """
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate or "@" not in candidate:
        return "***" if candidate else ""
    local, _, domain = candidate.partition("@")
    if not local or not domain:
        return "***"
    local_masked = (local[0] + "***") if local else "***"
    if "." in domain:
        host, _, tld = domain.rpartition(".")
        host_masked = (host[0] + "***") if host else "***"
        return "%s@%s.%s" % (local_masked, host_masked, tld)
    return "%s@%s***" % (local_masked, domain[0])


def mask_recipients(recipients: Iterable[str]) -> list[str]:
    """Mask every recipient in an iterable, preserving order.

    Non-string / empty entries are dropped. Returns a list of masked strings
    safe to log or persist.
    """
    if recipients is None:
        return []
    masked: list[str] = []
    for item in recipients:
        if not isinstance(item, str):
            continue
        out = mask_email(item)
        if out:
            masked.append(out)
    return masked
