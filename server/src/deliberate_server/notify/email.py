"""Email notification adapter using aiosmtplib (PRD §6.2 Draft v4).

Sends HTML email with approval preview and "Review and decide" button.
Retries 3x with backoff on connection failure; fails immediately on auth error.
"""

from __future__ import annotations

import asyncio
import logging
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import ClassVar

import aiosmtplib

from deliberate_server.config import settings
from deliberate_server.notify.base import NotificationContext, NotificationResult

logger = logging.getLogger("deliberate_server.notify.email")

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # seconds
SMTP_TIMEOUT = 30


class EmailNotifier:
    """Sends approval notifications via SMTP email."""

    channel_name: ClassVar[str] = "email"

    async def send(self, ctx: NotificationContext) -> NotificationResult:
        """Send an email notification for a pending approval."""
        if not settings.smtp_host:
            return NotificationResult(
                channel=self.channel_name,
                success=False,
                error="SMTP_HOST not configured",
                duration_ms=0,
            )

        msg = self._build_message(ctx)
        start = time.monotonic()

        last_error: str | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await aiosmtplib.send(
                    msg,
                    hostname=settings.smtp_host,
                    port=settings.smtp_port,
                    username=settings.smtp_username or None,
                    password=settings.smtp_password or None,
                    use_tls=settings.smtp_use_tls,
                    timeout=SMTP_TIMEOUT,
                )
                duration = int((time.monotonic() - start) * 1000)
                # response is a tuple of (response_dict, message_text)
                message_id = msg["Message-ID"] or ""
                logger.info(
                    "Email sent to %s for approval %s (attempt %d)",
                    ctx.approver.email,
                    ctx.approval_id,
                    attempt + 1,
                )
                return NotificationResult(
                    channel=self.channel_name,
                    success=True,
                    message_id=message_id,
                    duration_ms=duration,
                )
            except aiosmtplib.SMTPAuthenticationError as e:
                # Auth errors: fail immediately, don't retry
                duration = int((time.monotonic() - start) * 1000)
                logger.error("SMTP auth error: %s", e)
                return NotificationResult(
                    channel=self.channel_name,
                    success=False,
                    error=f"SMTP authentication failed: {e}",
                    duration_ms=duration,
                )
            except (aiosmtplib.SMTPException, OSError, asyncio.TimeoutError) as e:
                last_error = str(e)
                logger.warning(
                    "SMTP send attempt %d/%d failed for %s: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    ctx.approver.email,
                    e,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BACKOFF_BASE ** attempt)

        duration = int((time.monotonic() - start) * 1000)
        return NotificationResult(
            channel=self.channel_name,
            success=False,
            error=f"SMTP send failed after {MAX_RETRIES} attempts: {last_error}",
            duration_ms=duration,
        )

    async def health_check(self) -> bool:
        """Check if SMTP is configured."""
        return bool(settings.smtp_host)

    def _build_message(self, ctx: NotificationContext) -> MIMEMultipart:
        """Build the email MIME message with HTML and plain-text parts."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Deliberate] Approval needed: {ctx.subject}"
        msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        msg["To"] = ctx.approver.email

        # Build evidence/reasoning preview
        reasoning_html = ""
        reasoning_text = ""
        reasoning = ctx.payload_preview.get("agent_reasoning")
        if reasoning:
            if isinstance(reasoning, dict) and "summary" in reasoning:
                reasoning_html = f"<p><strong>Agent reasoning:</strong> {_escape(str(reasoning['summary']))}</p>"
                reasoning_text = f"Agent reasoning: {reasoning['summary']}"
            elif isinstance(reasoning, str):
                reasoning_html = f"<p><strong>Agent reasoning:</strong> {_escape(reasoning)}</p>"
                reasoning_text = f"Agent reasoning: {reasoning}"

        amount_html = ""
        amount_text = ""
        amount = ctx.payload_preview.get("amount")
        if isinstance(amount, dict) and "value" in amount:
            currency = amount.get("currency", "USD")
            amount_html = f"<p><strong>Amount:</strong> {currency} {amount['value']}</p>"
            amount_text = f"Amount: {currency} {amount['value']}"

        expires_text = ""
        if ctx.expires_at:
            expires_text = f"Expires at {ctx.expires_at.strftime('%Y-%m-%d %H:%M UTC')}"

        # Plain-text version
        plain = f"""Approval needed: {ctx.subject}

{amount_text}
{reasoning_text}

Review and decide: {ctx.approval_url}

{expires_text}
This is an approval request from Deliberate."""

        # HTML version
        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="border-bottom: 3px solid #2563eb; padding-bottom: 16px; margin-bottom: 24px;">
    <h2 style="margin: 0; color: #1e293b;">{_escape(ctx.subject)}</h2>
  </div>

  {amount_html}
  {reasoning_html}

  <div style="margin: 32px 0; text-align: center;">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center">
      <tr>
        <td style="border-radius: 6px; background-color: #2563eb;">
          <a href="{ctx.approval_url}"
             style="display: inline-block; padding: 14px 32px; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 16px;"
             target="_blank">
            Review and decide
          </a>
        </td>
      </tr>
    </table>
  </div>

  <div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #e2e8f0; color: #64748b; font-size: 13px;">
    <p>This is an approval request from Deliberate.{(' ' + expires_text + '.') if expires_text else ''}</p>
  </div>
</body>
</html>"""

        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        return msg


def _escape(text: str) -> str:
    """Basic HTML escaping for user-provided text."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
