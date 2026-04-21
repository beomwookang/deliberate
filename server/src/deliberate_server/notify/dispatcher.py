"""Notification dispatcher — fans out to configured channels in parallel.

Takes a ResolvedPlan and fires notifications to each approver across
each requested channel. Individual channel failures don't block others.
Results are logged to notification_attempts for ops visibility.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from deliberate_server.db.models import NotificationAttempt
from deliberate_server.db.session import async_session
from deliberate_server.notify.base import (
    NotificationContext,
    NotificationResult,
    Notifier,
    build_payload_preview,
)
from deliberate_server.policy.types import ResolvedPlan

logger = logging.getLogger("deliberate_server.notify.dispatcher")


class NotificationDispatcher:
    """Dispatches notifications to approvers via configured channels."""

    def __init__(self) -> None:
        self._adapters: dict[str, Notifier] = {}

    def register(self, adapter: Notifier) -> None:
        """Register a notification adapter."""
        self._adapters[adapter.channel_name] = adapter
        logger.info("Registered notification adapter: %s", adapter.channel_name)

    async def dispatch(
        self,
        plan: ResolvedPlan,
        approval_id: UUID,
        application_id: str,
        payload: dict[str, Any],
        approval_url: str,
    ) -> list[NotificationResult]:
        """Fire notifications to all approvers across all requested channels.

        Returns aggregated results. Failures are logged but don't raise.
        """
        if plan.action == "auto_approve":
            return []

        if not plan.notify_channels:
            logger.info("No notification channels configured for plan %s", plan.matched_rule_name)
            return []

        preview = build_payload_preview(payload)
        layout = payload.get("layout", "unknown")
        subject = payload.get("subject", "Approval needed")

        # Determine expiry from timeout
        expires_at: datetime | None = None
        if plan.timeout_seconds:
            expires_at = datetime.now(UTC) + timedelta(seconds=plan.timeout_seconds)

        # Build all (approver, channel) combinations
        tasks: list[asyncio.Task[NotificationResult]] = []

        for approver in plan.approvers:
            for channel_name in plan.notify_channels:
                adapter = self._adapters.get(channel_name)
                if adapter is None:
                    logger.warning(
                        "No adapter registered for channel '%s' — skipping notification "
                        "for approver %s",
                        channel_name,
                        approver.email,
                    )
                    continue

                ctx = NotificationContext(
                    approval_id=approval_id,
                    approver=approver,
                    layout=layout,
                    subject=subject,
                    approval_url=approval_url,
                    payload_preview=preview,
                    expires_at=expires_at,
                )

                task = asyncio.create_task(
                    self._send_safe(adapter, ctx, application_id),
                    name=f"notify-{channel_name}-{approver.email}",
                )
                tasks.append(task)

        if not tasks:
            return []

        # Fire all in parallel
        results = await asyncio.gather(*tasks)
        results_list = list(results)

        # Log summary
        successes = sum(1 for r in results_list if r.success)
        failures = len(results_list) - successes
        logger.info(
            "Notification dispatch complete for approval %s: %d/%d succeeded",
            approval_id,
            successes,
            len(results_list),
        )
        if failures > 0:
            for r in results_list:
                if not r.success:
                    logger.warning("Notification failed: channel=%s, error=%s", r.channel, r.error)

        return results_list

    async def _send_safe(
        self,
        adapter: Notifier,
        ctx: NotificationContext,
        application_id: str,
    ) -> NotificationResult:
        """Send a notification and record the attempt. Never raises."""
        try:
            result = await adapter.send(ctx)
        except Exception as e:
            logger.error(
                "Notification adapter %s raised unexpected error: %s",
                adapter.channel_name,
                e,
                exc_info=True,
            )
            result = NotificationResult(
                channel=adapter.channel_name,
                success=False,
                error=str(e),
                duration_ms=0,
            )

        # Persist to notification_attempts table
        try:
            async with async_session() as session, session.begin():
                attempt = NotificationAttempt(
                    id=uuid.uuid4(),
                    application_id=application_id,
                    approval_id=ctx.approval_id,
                    channel=result.channel,
                    approver_email=ctx.approver.email,
                    success=result.success,
                    message_id=result.message_id,
                    error=result.error,
                    duration_ms=result.duration_ms,
                    attempted_at=datetime.now(UTC),
                )
                session.add(attempt)
        except Exception as e:
            # Don't let DB write failure cascade
            logger.error("Failed to record notification attempt: %s", e)

        return result
