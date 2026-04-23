"""Startup seeding and admin bootstrap utilities.

Called during server startup to populate policies, approvers, and admin API keys
from YAML config files when the database is empty.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from deliberate_server.auth import generate_api_key
from deliberate_server.db.models import ApiKey, Approver, ApproverGroup, PolicyRecord, PolicyVersion

logger = logging.getLogger("deliberate_server.seeding")


def _content_hash(content: dict[str, Any]) -> str:
    """Compute sha256: + SHA-256 of canonical JSON (sorted keys, compact separators)."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


async def seed_from_yaml_if_empty(
    session: AsyncSession,
    policies_dir: str,
    approvers_file: str,
) -> None:
    """Seed policies and approvers from YAML files if the DB tables are empty.

    Policy seeding: loads each *.yaml from policies_dir, creates PolicyRecord + PolicyVersion.
    Approver seeding: loads approvers_file, creates Approver + ApproverGroup rows.
    Skips each section if rows already exist. Commits at the end.
    """
    # --- Policy seeding ---
    policy_count_result = await session.execute(select(func.count()).select_from(PolicyRecord))
    policy_count = policy_count_result.scalar_one()

    if policy_count > 0:
        logger.info("Skipping policy seeding — %d policies already exist.", policy_count)
    else:
        policies_path = Path(policies_dir)
        if not policies_path.is_dir():
            logger.warning(
                "Policies directory %s does not exist — skipping policy seeding.",
                policies_dir,
            )
        else:
            yaml_files = sorted(policies_path.glob("*.yaml"))
            seeded = 0
            for yaml_file in yaml_files:
                with open(yaml_file) as f:
                    definition = yaml.safe_load(f)
                if not definition or "name" not in definition:
                    logger.warning("Skipping %s — missing 'name' field.", yaml_file)
                    continue
                content_hash = _content_hash(definition)
                policy_id = uuid.uuid4()
                policy = PolicyRecord(
                    id=policy_id,
                    name=definition["name"],
                    version=1,
                    definition=definition,
                    content_hash=content_hash,
                    created_by="seed",
                    is_active=True,
                )
                session.add(policy)
                version = PolicyVersion(
                    id=uuid.uuid4(),
                    policy_id=policy_id,
                    version=1,
                    definition=definition,
                    content_hash=content_hash,
                    changed_by="seed",
                    change_reason="Initial seed from YAML",
                )
                session.add(version)
                seeded += 1
                logger.info("Seeded policy '%s' from %s.", definition["name"], yaml_file.name)
            logger.info("Policy seeding complete — %d policies seeded.", seeded)

    # --- Approver seeding ---
    approver_count_result = await session.execute(select(func.count()).select_from(Approver))
    approver_count = approver_count_result.scalar_one()

    if approver_count > 0:
        logger.info("Skipping approver seeding — %d approvers already exist.", approver_count)
    else:
        approvers_path = Path(approvers_file)
        if not approvers_path.is_file():
            logger.warning(
                "Approvers file %s does not exist — skipping approver seeding.",
                approvers_file,
            )
        else:
            with open(approvers_path) as f:
                data = yaml.safe_load(f)

            approvers_seeded = 0
            for entry in data.get("approvers", []):
                approver = Approver(
                    id=entry["id"],
                    email=entry["email"],
                    display_name=entry.get("display_name"),
                    is_active=True,
                    ooo_active=False,
                )
                session.add(approver)
                approvers_seeded += 1

            groups_seeded = 0
            for group in data.get("groups", []):
                approver_group = ApproverGroup(
                    id=group["id"],
                    members=group.get("members", []),
                    is_active=True,
                )
                session.add(approver_group)
                groups_seeded += 1

            logger.info(
                "Approver seeding complete — %d approvers, %d groups seeded.",
                approvers_seeded,
                groups_seeded,
            )

    await session.commit()


async def bootstrap_admin_key(session: AsyncSession, bootstrap_secret: str) -> str | None:
    """Create the first admin API key if none exists.

    Checks for any non-revoked key with 'policies:write' scope. If one already
    exists, returns None (idempotent). Otherwise creates a full-scoped admin key,
    logs the raw key as WARNING, and returns the raw key.
    """
    result = await session.execute(
        select(ApiKey).where(
            text("scopes @> ARRAY['policies:write']"),
            ApiKey.revoked_at.is_(None),
        )
    )
    existing = result.scalars().first()
    if existing is not None:
        logger.info(
            "Admin key already exists (prefix=%s) — skipping bootstrap.",
            existing.key_prefix,
        )
        return None

    raw_key, key_prefix, key_hash_value = generate_api_key()
    admin_key = ApiKey(
        id=uuid.uuid4(),
        name="bootstrap-admin",
        key_prefix=key_prefix,
        key_hash=key_hash_value,
        scopes=[
            "interrupts:write",
            "approvals:read",
            "approvals:write",
            "policies:read",
            "policies:write",
            "approvers:read",
            "approvers:write",
            "api_keys:read",
            "api_keys:write",
            "ledger:read",
            "ledger:export",
        ],
        created_by=bootstrap_secret[:8] + "...",
    )
    session.add(admin_key)
    await session.commit()

    logger.warning(
        "BOOTSTRAP ADMIN KEY CREATED — save this key now, it will not be shown again: %s",
        raw_key,
    )
    return raw_key
