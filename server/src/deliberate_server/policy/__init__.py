"""Policy subsystem — engine, directory, and expression evaluator.

The global policy engine and approver directory are initialized at import time
from server configuration. They are used by the interrupt handler.
"""

from __future__ import annotations

import logging
from pathlib import Path

from deliberate_server.config import settings
from deliberate_server.policy.directory import ApproverDirectory, ApproverDirectoryError
from deliberate_server.policy.engine import NoMatchingPolicyError, PolicyEngine, PolicyLoadError

logger = logging.getLogger("deliberate_server.policy")

# Global instances — initialized once, used by request handlers
approver_directory = ApproverDirectory()
policy_engine = PolicyEngine(approver_directory)


def init_policy_system() -> None:
    """Initialize the policy engine, approver directory, and notification system.

    Called at application startup. Gracefully handles missing config files
    when DEFAULT_APPROVER_EMAIL fallback is available.
    """
    approvers_path = Path(settings.approvers_file)
    policies_path = Path(settings.policies_dir)

    # Load approver directory
    if approvers_path.exists():
        try:
            approver_directory.load(approvers_path)
            approver_directory.start_watching()
        except ApproverDirectoryError as e:
            logger.error("Failed to load approver directory: %s", e)
            if not settings.default_approver_email:
                raise
            logger.warning(
                "Falling back to DEFAULT_APPROVER_EMAIL=%s", settings.default_approver_email
            )
    elif not settings.default_approver_email:
        logger.warning(
            "No approver directory at %s and no DEFAULT_APPROVER_EMAIL set. "
            "Policy evaluation will fail for all interrupts.",
            approvers_path,
        )
    else:
        logger.info(
            "No approver directory at %s — using DEFAULT_APPROVER_EMAIL fallback.",
            approvers_path,
        )

    # Load policies
    if policies_path.exists() and policies_path.is_dir():
        try:
            policy_engine.load_policies(policies_path)
        except PolicyLoadError as e:
            logger.error("Failed to load policies: %s", e)
            if not settings.default_approver_email:
                raise
            logger.warning("Falling back to DEFAULT_APPROVER_EMAIL for all interrupts.")
    elif not settings.default_approver_email:
        logger.warning(
            "No policies directory at %s and no DEFAULT_APPROVER_EMAIL set. "
            "All interrupts will fail.",
            policies_path,
        )
    else:
        logger.info(
            "No policies directory at %s — using DEFAULT_APPROVER_EMAIL fallback.",
            policies_path,
        )

    # Initialize notification adapters
    from deliberate_server.notify import init_notification_system

    init_notification_system()


__all__ = [
    "ApproverDirectory",
    "NoMatchingPolicyError",
    "PolicyEngine",
    "PolicyLoadError",
    "approver_directory",
    "init_policy_system",
    "policy_engine",
]
