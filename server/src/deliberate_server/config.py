"""Environment-driven configuration using pydantic-settings.

See PRD §6.7 for the expected environment variables.
"""

from __future__ import annotations

import logging
import sys

from pydantic_settings import BaseSettings

logger = logging.getLogger("deliberate_server.config")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql+asyncpg://deliberate:deliberate@localhost:5432/deliberate"

    # Server
    secret_key: str = ""  # Must be set — server fails to start if empty
    server_host: str = "0.0.0.0"
    server_port: int = 4000

    # M1 fallback: single approver from env var (deprecated — use policies)
    default_approver_email: str = ""

    # UI URL for constructing approval links
    ui_url: str = "http://localhost:3000"

    # Policy engine (M2a)
    approvers_file: str = "config/approvers.yaml"  # DELIBERATE_APPROVERS_FILE
    policies_dir: str = "config/policies"  # DELIBERATE_POLICIES_DIR
    webhooks_file: str = "config/webhooks.yaml"  # DELIBERATE_WEBHOOKS_FILE

    # Slack (optional)
    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    # Email / SMTP (optional)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@example.com"
    smtp_from_name: str = "Deliberate"
    smtp_use_tls: bool = True

    # Webhook (optional — per-webhook secrets are in webhooks.yaml)
    webhook_signing_secret: str = ""

    # Worker
    worker_poll_interval_seconds: int = 15
    max_escalation_depth: int = 3

    model_config = {"env_prefix": "", "case_sensitive": False}


def get_settings() -> Settings:
    """Load and validate settings. Fails fast on missing required values."""
    s = Settings()
    if not s.secret_key:
        print(
            "FATAL: SECRET_KEY environment variable is not set. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"',
            file=sys.stderr,
        )
        sys.exit(1)
    if s.default_approver_email:
        logger.warning(
            "DEFAULT_APPROVER_EMAIL is deprecated. "
            "Use YAML policies in %s instead. "
            "The env var fallback will be removed in v0.3.0.",
            s.policies_dir,
        )
    return s


settings = get_settings()
