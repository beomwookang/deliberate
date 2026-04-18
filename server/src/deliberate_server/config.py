"""Environment-driven configuration using pydantic-settings.

See PRD §6.7 for the expected environment variables.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql+asyncpg://deliberate:deliberate@localhost:5432/deliberate"

    # Server
    secret_key: str = "change-me-to-a-random-secret"
    server_host: str = "0.0.0.0"
    server_port: int = 4000

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


settings = Settings()
