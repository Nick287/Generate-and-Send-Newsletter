"""
EmailDispatcher — sends the newsletter via ACS, SendGrid, or SMTP.
EmailDispatcher — 通过ACS、SendGrid或SMTP发送新闻简报。

This is Stage 5 of the newsletter pipeline.
这是新闻简报流水线的第5阶段。

Supported providers:
支持的提供商：
- ACS (Azure Communication Services) — default   | ACS（Azure通信服务）— 默认
- SendGrid — via REST API                         | SendGrid — 通过REST API
- SMTP — reuses function/EmailSender.EmailSender   | SMTP — 复用function/EmailSender.EmailSender

Reuses ``function.EmailSender.EmailSender`` for SMTP delivery.
复用 ``function.EmailSender.EmailSender`` 进行SMTP发送。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from core.models import AppConfig
from core.paths import ACS_SECRET_FILE, DATA_DIR
from core.utils import (
    email_client_class,
    log_event,
    utc_now,
)

# Reuse the EmailSender from function/ for SMTP delivery
from function.EmailSender import EmailSender


class EmailDispatcher:
    """Sends the newsletter email through the configured provider (ACS / SendGrid / SMTP).
    通过配置的提供商(ACS/SendGrid/SMTP)发送新闻简报邮件。
    """

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger

    # ── public API | 公开接口 ───────────────────────────────────────────
    def send(
        self,
        recipients: list[str],
        subject: str,
        html_body: str,
        date_label: str,
    ) -> tuple[bool, str]:
        """Send the newsletter email with retry (up to 2 attempts).
        发送新闻简报邮件，支持重试(最多2次)。
        Returns (success_flag, detail_message). | 返回 (成功标志, 详情消息)。
        """
        provider = (self.config.email_provider or "acs").lower()
        print("--- Step: Sending newsletter email (provider=%s) ---" % provider)
        print("    Recipients: %s" % ", ".join(recipients))

        last_error = ""
        for attempt in range(1, 3):
            try:
                result = self._do_send(provider, recipients, subject, html_body)
                status = str(result.get("status") or "").lower()
                if status in {"succeeded", "success"}:
                    detail = "%s send succeeded (%s)" % (provider, result.get("id") or "no-id")
                    self._append_send_log(
                        {
                            "date": date_label,
                            "subject": subject,
                            "recipients": recipients,
                            "status": "success",
                            "detail": detail,
                            "provider": provider,
                            "result": result,
                            "ts": utc_now().isoformat(),
                        }
                    )
                    log_event(
                        self.logger, logging.INFO, "send_success",
                        recipients=recipients, detail=detail, provider=provider,
                    )
                    print("    Email sent successfully: %s" % detail)
                    return True, detail
                last_error = "%s send returned status=%s" % (
                    provider,
                    result.get("status") or "unknown",
                )
                log_event(
                    self.logger, logging.WARNING, "send_retry",
                    attempt=attempt, error=last_error,
                )
                print("    Attempt %d failed: %s" % (attempt, last_error))
            except Exception as exc:
                last_error = str(exc)
                log_event(
                    self.logger, logging.WARNING, "send_retry",
                    attempt=attempt, error=last_error,
                )
                print("    Attempt %d exception: %s" % (attempt, last_error))
            if attempt < 2:
                time.sleep(10)

        self._append_send_log(
            {
                "date": date_label,
                "subject": subject,
                "recipients": recipients,
                "status": "failed",
                "detail": last_error,
                "provider": provider,
                "ts": utc_now().isoformat(),
            }
        )
        log_event(
            self.logger, logging.ERROR, "send_failed",
            error=last_error, provider=provider,
        )
        print("    Email sending FAILED after all retries: %s" % last_error)
        return False, last_error

    # ── internal dispatch | 内部分发 ────────────────────────────────────
    def _do_send(
        self,
        provider: str,
        recipients: list[str],
        subject: str,
        html_body: str,
    ) -> dict[str, Any]:
        """Route to the appropriate provider-specific send method.
        路由到相应的提供商特定发送方法。
        """
        if provider == "sendgrid":
            return self._send_via_sendgrid(recipients, subject, html_body)
        if provider == "smtp":
            return self._send_via_smtp(recipients, subject, html_body)
        # default: ACS
        return self._send_via_acs(recipients, subject, html_body)

    # ── ACS | Azure通信服务 ────────────────────────────────────────────
    def _send_via_acs(
        self, recipients: list[str], subject: str, html_body: str
    ) -> dict[str, Any]:
        """Send email using Azure Communication Services (ACS).
        使用Azure通信服务(ACS)发送邮件。
        """
        connection_string = self._read_acs_connection_string()
        if not connection_string:
            raise RuntimeError("ACS connection string not found in env or config")
        client = email_client_class().from_connection_string(connection_string)
        message = {
            "senderAddress": self.config.acs_sender,
            "recipients": {"to": [{"address": item} for item in recipients]},
            "content": {
                "subject": subject,
                "html": html_body,
                "plainText": "AI Weekly Digest HTML email",
            },
        }
        poller = client.begin_send(message)
        result = poller.result()
        if isinstance(result, dict):
            return result
        as_dict = getattr(result, "as_dict", None)
        if callable(as_dict):
            converted = as_dict()
            if isinstance(converted, dict):
                return converted
        return {
            "status": getattr(result, "status", None),
            "id": getattr(result, "id", None),
        }

    # ── SendGrid | SendGrid邮件服务 ─────────────────────────────────────
    def _send_via_sendgrid(
        self, recipients: list[str], subject: str, html_body: str
    ) -> dict[str, Any]:
        """Send email using SendGrid REST API.
        使用SendGrid REST API发送邮件。
        """
        api_key = os.environ.get("SENDGRID_API_KEY", "") or self.config.sendgrid_api_key
        if not api_key:
            raise RuntimeError("SENDGRID_API_KEY not set")
        sender = self.config.acs_sender or os.environ.get("EMAIL_SENDER", "")
        if not sender:
            raise RuntimeError("email sender (acs_sender or EMAIL_SENDER) not set")
        payload = {
            "personalizations": [{"to": [{"email": r} for r in recipients]}],
            "from": {"email": sender},
            "subject": subject,
            "content": [{"type": "text/html", "value": html_body}],
        }
        resp = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={
                "Authorization": "Bearer %s" % api_key,
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        if resp.status_code in (200, 202):
            return {"status": "succeeded", "id": resp.headers.get("X-Message-Id")}
        return {"status": "failed", "detail": resp.text[:300]}

    # ── SMTP (复用 function/EmailSender) | SMTP（复用function/EmailSender）────
    def _send_via_smtp(
        self, recipients: list[str], subject: str, html_body: str
    ) -> dict[str, Any]:
        """Send email using SMTP via the shared EmailSender utility.
        使用共享EmailSender工具通过SMTP发送邮件。
        """
        host = self.config.smtp_host
        port = self.config.smtp_port
        user = self.config.smtp_user
        pw = self.config.smtp_pass
        sender = self.config.acs_sender or user
        if not host or not sender:
            raise RuntimeError("SMTP host/sender not configured")

        # Auto-detect SSL for common SSL ports (465)
        # 常见SSL端口(465)自动检测SSL
        use_ssl = self.config.smtp_use_ssl or port == 465

        print("    Using function/EmailSender for SMTP delivery ...")
        email_sender = EmailSender(
            smtp_host=host,
            smtp_port=port,
            username=user,
            password=pw,
            use_ssl=use_ssl,
            use_tls=not use_ssl,
            max_retries=3,
            retry_delay=10,
        )
        from_alias = self.config.from_alias or "AI Weekly Digest"
        success = email_sender.send_email(
            to_addrs=recipients,
            subject=subject,
            body_html=html_body,
            from_alias=from_alias,
        )
        if success:
            return {"status": "succeeded", "id": "smtp"}
        return {"status": "failed", "detail": "EmailSender failed after retries"}

    # ── helpers ──────────────────────────────────────────────────────────────
    def _read_acs_connection_string(self) -> str | None:
        value = os.environ.get("ACS_CONNECTION_STRING")
        if value and value.strip():
            return value.strip()
        if getattr(self.config, "acs_connection_string", ""):
            return self.config.acs_connection_string
        if ACS_SECRET_FILE is not None and ACS_SECRET_FILE.exists():
            try:
                content = ACS_SECRET_FILE.read_text(encoding="utf-8").strip()
                return content or None
            except Exception:
                return None
        return None

    def _append_send_log(self, entry: dict[str, Any]) -> None:
        """Append a send result entry to data/send-log.json.
        将发送结果条目追加到 data/send-log.json。
        """
        path = DATA_DIR / "send-log.json"
        existing: list[Any] = []
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    existing = raw
            except Exception as exc:
                log_event(
                    self.logger, logging.WARNING, "send_log_load_failed", error=str(exc)
                )
        existing.append(entry)
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
