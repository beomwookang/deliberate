"""Notification subsystem — adapters and dispatcher.

The global dispatcher is initialized at import time and adapters are
registered during policy system init.
"""

from __future__ import annotations

import logging

from deliberate_server.notify.dispatcher import NotificationDispatcher
from deliberate_server.notify.email import EmailNotifier
from deliberate_server.notify.slack import SlackNotifier
from deliberate_server.notify.webhook import WebhookNotifier

logger = logging.getLogger("deliberate_server.notify")

# Global dispatcher instance
notification_dispatcher = NotificationDispatcher()


def init_notification_system() -> None:
    """Register all notification adapters. Called at application startup."""
    from deliberate_server.config import settings

    # Email adapter — always registered, fails gracefully if SMTP not configured
    notification_dispatcher.register(EmailNotifier())

    # Webhook adapter — load configs from webhooks.yaml
    webhook = WebhookNotifier()
    webhook.load_configs()
    notification_dispatcher.register(webhook)

    # Slack adapter — always registered, fails gracefully if token not set
    notification_dispatcher.register(SlackNotifier())

    logger.info(
        "Notification system initialized with %d adapters",
        len(notification_dispatcher._adapters),
    )


__all__ = [
    "NotificationDispatcher",
    "init_notification_system",
    "notification_dispatcher",
]
