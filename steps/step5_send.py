#!/usr/bin/env python3
"""
Step 5: Send Email — 发送邮件

Input:  HTML body (from step4) + config
Output: data/send-log.json (appended)

通过ACS/SendGrid/SMTP发送新闻简报邮件。
Sends the newsletter email via ACS / SendGrid / SMTP.

Usage:
    python -m steps.step5_send
    python -m steps.step5_send --date 2026-04-24 --to user@example.com
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.models import AppConfig
from core.utils import (
    ensure_directories,
    setup_logging,
    today_label,
    week_range_label,
)
from core.email_dispatcher import EmailDispatcher


# ── step function | 步骤函数 ─────────────────────────────────────────────────

def run(
    config: AppConfig,
    recipients: list[str],
    subject: str,
    html_body: str,
    date_label: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    """
    Send newsletter email.
    发送新闻简报邮件。

    Returns dict:
        success:  bool   — whether email was sent successfully
        detail:   str    — status detail message
    """
    print()
    print("=" * 60)
    print("  STEP 5 / 5 : SEND EMAIL")
    print("=" * 60)

    dispatcher = EmailDispatcher(config, logger)
    send_ok, send_detail = dispatcher.send(recipients, subject, html_body, date_label)

    return {
        "success": send_ok,
        "detail": send_detail,
    }


# ── standalone entry | 独立入口 ──────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Step 5: Send email")
    parser.add_argument("--date", help="Date label (default: today)")
    parser.add_argument("--to", help="Override recipient email(s), comma-separated")
    args = parser.parse_args()

    from steps.step0_config import run as load_config
    from steps.step1_fetch import run as fetch
    from steps.step2_enrich import run as enrich
    from steps.step3_curate import run as curate
    from steps.step4_compose import run as compose

    ctx = load_config(date_label=args.date)
    config = ctx["config"]

    fetch_result = fetch(config, ctx["feeds"], ctx["date_label"], ctx["logger"])
    if fetch_result["abort"]:
        print("\n❌ Cannot send: %s" % fetch_result["abort_message"])
        return 2

    enrich_result = enrich(config, fetch_result["articles"], ctx["date_label"], ctx["logger"])
    curate_result = curate(config, enrich_result["articles"], ctx["date_label"], ctx["logger"])
    compose_result = compose(
        config, curate_result["stories"], fetch_result["articles"],
        ctx["date_label"], ctx["logger"],
    )

    # Resolve recipients
    if args.to and args.to.strip():
        recipients = [r.strip() for r in args.to.split(",") if r.strip()]
    else:
        recipients = list(config.recipients)

    subject = "AI Weekly Digest — Week of %s" % (
        week_range_label(window_days=config.fetch_window_days),
    )

    result = run(config, recipients, subject, compose_result["html_body"], ctx["date_label"], ctx["logger"])
    if result["success"]:
        print("\n✅ Email sent: %s" % result["detail"])
        return 0
    print("\n❌ Email failed: %s" % result["detail"])
    return 2


if __name__ == "__main__":
    sys.exit(main())
