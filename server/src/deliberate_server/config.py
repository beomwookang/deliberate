"""Environment-driven configuration using pydantic-settings.

See PRD §6.7 for the expected environment variables.
"""

from __future__ import annotations

import sys

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql+asyncpg://deliberate:deliberate@localhost:5432/deliberate"

    # Server
    secret_key: str = ""  # Must be set — server fails to start if empty
    server_host: str = "0.0.0.0"
    server_port: int = 4000

    # M1: single approver from env var (no policy engine yet)
    default_approver_email: str = ""

    # UI URL for constructing approval links in logs
    ui_url: str = "http://localhost:3000"

    # Slack (optional)
    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    # Email / SMTP (optional)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@example.com"

    # Webhook (optional)
    webhook_signing_secret: str = ""

    # Policy
    policy_directory: str = "policies"

    # Worker
    worker_poll_interval_seconds: int = 15

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
    if not s.default_approver_email:
        print(
            "WARNING: DELIBERATE_DEFAULT_APPROVER_EMAIL is not set. "
            "M1 requires a single approver email in this env var.",
            file=sys.stderr,
        )
    return s


settings = get_settings()
