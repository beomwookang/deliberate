"""Policy CRUD API (PRD §5.2).

Provides create, read, update, delete, test, and version-history endpoints
for policies stored in the database.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from deliberate_server.api.deps import authenticate_api_key
from deliberate_server.db.models import PolicyRecord, PolicyVersion
from deliberate_server.db.session import async_session
from deliberate_server.policy import policy_engine
from deliberate_server.policy.evaluator import evaluate
from deliberate_server.policy.parser import ParseError, parse_expression

logger = logging.getLogger("deliberate_server.api.policies")

router = APIRouter(prefix="/policies", tags=["policies"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _content_hash(definition: dict[str, Any]) -> str:
    """Compute sha256: + SHA-256 of canonical JSON (sorted keys, compact)."""
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"sha256:{digest}"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ApproverSpecBody(BaseModel):
    any_of: list[str] | None = None
    all_of: list[str] | None = None


class RuleBody(BaseModel):
    name: str
    when: str
    action: str | None = None
    rationale: str | None = None
    approvers: ApproverSpecBody | None = None
    timeout: str | None = None
    notify: list[str] = []


class PolicyCreateRequest(BaseModel):
    name: str
    matches: dict[str, Any]
    rules: list[RuleBody]


class PolicyUpdateRequest(BaseModel):
    matches: dict[str, Any]
    rules: list[RuleBody]
    change_reason: str | None = None


class PolicyListItem(BaseModel):
    name: str
    version: int
    rule_count: int
    content_hash: str
    updated_at: datetime


class PolicyDetail(BaseModel):
    name: str
    version: int
    definition: dict[str, Any]
    content_hash: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class PolicyWriteResponse(BaseModel):
    name: str
    version: int
    rules: list[dict[str, Any]]
    content_hash: str


class PolicyTestRequest(BaseModel):
    payload: dict[str, Any]


class PolicyTestResponse(BaseModel):
    matched: bool
    matched_rule: str | None = None
    action: str | None = None
    approvers: dict[str, Any] | None = None
    timeout: str | None = None


class PolicyVersionItem(BaseModel):
    version: int
    content_hash: str
    changed_by: str
    change_reason: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[PolicyListItem])
async def list_policies(
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> list[PolicyListItem]:
    """List all active policies."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="policies:read")
        result = await session.execute(select(PolicyRecord).where(PolicyRecord.is_active.is_(True)))
        records = result.scalars().all()

    return [
        PolicyListItem(
            name=r.name,
            version=r.version,
            rule_count=len(r.definition.get("rules", [])),
            content_hash=r.content_hash,
            updated_at=r.updated_at,
        )
        for r in records
    ]


@router.get("/{name}", response_model=PolicyDetail)
async def get_policy(
    name: str,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> PolicyDetail:
    """Get a policy by name. Returns 404 if not found or inactive."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="policies:read")
        result = await session.execute(
            select(PolicyRecord).where(
                PolicyRecord.name == name,
                PolicyRecord.is_active.is_(True),
            )
        )
        record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(status_code=404, detail=f"Policy '{name}' not found")

    return PolicyDetail(
        name=record.name,
        version=record.version,
        definition=record.definition,
        content_hash=record.content_hash,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.post("", response_model=PolicyWriteResponse, status_code=201)
async def create_policy(
    body: PolicyCreateRequest,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> PolicyWriteResponse:
    """Create a new policy. Returns 409 if name already exists."""
    definition: dict[str, Any] = {
        "name": body.name,
        "matches": body.matches,
        "rules": [r.model_dump(exclude_none=True) for r in body.rules],
    }
    content_hash = _content_hash(definition)
    now = datetime.now(UTC)

    async with async_session() as session, session.begin():
        api_key = await authenticate_api_key(
            x_deliberate_api_key, session, required_scope="policies:write"
        )
        # Check for existing active policy with this name
        existing = await session.execute(
            select(PolicyRecord).where(
                PolicyRecord.name == body.name,
                PolicyRecord.is_active.is_(True),
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"Policy '{body.name}' already exists")

        record = PolicyRecord(
            application_id="default",
            name=body.name,
            version=1,
            definition=definition,
            content_hash=content_hash,
            created_by=api_key.name,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(record)

    async with async_session() as session:
        await policy_engine.load_from_db(session)

    logger.info("Created policy '%s' (v1) by %s", body.name, api_key.name)

    return PolicyWriteResponse(
        name=body.name,
        version=1,
        rules=[r.model_dump(exclude_none=True) for r in body.rules],
        content_hash=content_hash,
    )


@router.put("/{name}", response_model=PolicyWriteResponse)
async def update_policy(
    name: str,
    body: PolicyUpdateRequest,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> PolicyWriteResponse:
    """Update a policy, incrementing its version. Saves old version to history."""
    async with async_session() as session, session.begin():
        api_key = await authenticate_api_key(
            x_deliberate_api_key, session, required_scope="policies:write"
        )
        result = await session.execute(
            select(PolicyRecord).where(
                PolicyRecord.name == name,
                PolicyRecord.is_active.is_(True),
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail=f"Policy '{name}' not found")

        new_version = record.version + 1
        new_definition: dict[str, Any] = {
            "name": name,
            "matches": body.matches,
            "rules": [r.model_dump(exclude_none=True) for r in body.rules],
        }
        new_hash = _content_hash(new_definition)
        now = datetime.now(UTC)

        # Save old version to history
        version_entry = PolicyVersion(
            policy_id=record.id,
            version=record.version,
            definition=record.definition,
            content_hash=record.content_hash,
            changed_by=api_key.name,
            change_reason=body.change_reason,
            created_at=now,
        )
        session.add(version_entry)

        # Update the policy record
        record.version = new_version
        record.definition = new_definition
        record.content_hash = new_hash
        record.updated_at = now
        session.add(record)

        # Trim versions older than 50 for this policy
        versions_result = await session.execute(
            select(PolicyVersion.id)
            .where(PolicyVersion.policy_id == record.id)
            .order_by(PolicyVersion.version.desc())
            .offset(50)
        )
        old_ids = [row[0] for row in versions_result.all()]
        if old_ids:
            await session.execute(delete(PolicyVersion).where(PolicyVersion.id.in_(old_ids)))

    async with async_session() as session:
        await policy_engine.load_from_db(session)

    logger.info("Updated policy '%s' to v%d by %s", name, new_version, api_key.name)

    return PolicyWriteResponse(
        name=name,
        version=new_version,
        rules=[r.model_dump(exclude_none=True) for r in body.rules],
        content_hash=new_hash,
    )


@router.delete("/{name}", status_code=204)
async def delete_policy(
    name: str,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> None:
    """Soft-delete a policy (is_active=False). Returns 404 if not found."""
    async with async_session() as session, session.begin():
        api_key = await authenticate_api_key(
            x_deliberate_api_key, session, required_scope="policies:write"
        )
        result = await session.execute(
            select(PolicyRecord).where(
                PolicyRecord.name == name,
                PolicyRecord.is_active.is_(True),
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail=f"Policy '{name}' not found")

        record.is_active = False
        record.updated_at = datetime.now(UTC)
        session.add(record)

    async with async_session() as session:
        await policy_engine.load_from_db(session)

    logger.info("Soft-deleted policy '%s' by %s", name, api_key.name)


@router.post("/{name}/test", response_model=PolicyTestResponse)
async def test_policy(
    name: str,
    body: PolicyTestRequest,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> PolicyTestResponse:
    """Dry-run: evaluate the policy's rules against a provided payload."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="policies:read")
        result = await session.execute(
            select(PolicyRecord).where(
                PolicyRecord.name == name,
                PolicyRecord.is_active.is_(True),
            )
        )
        record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(status_code=404, detail=f"Policy '{name}' not found")

    rules_raw: list[dict[str, Any]] = record.definition.get("rules", [])
    payload = body.payload

    for rule_dict in rules_raw:
        when_expr = rule_dict.get("when", "")
        try:
            ast = parse_expression(when_expr)
            matched = bool(evaluate(ast, payload))
        except (ParseError, Exception):
            matched = False

        if matched:
            # Build approvers dict directly from rule_dict to avoid Rule validation
            # rejecting action values like "request_human" (Rule.action is Literal["auto_approve"]).
            approvers_raw = rule_dict.get("approvers")
            action_raw: str = rule_dict.get("action") or "request_human"
            return PolicyTestResponse(
                matched=True,
                matched_rule=rule_dict.get("name", ""),
                action=action_raw,
                approvers=approvers_raw if isinstance(approvers_raw, dict) else None,
                timeout=rule_dict.get("timeout"),
            )

    return PolicyTestResponse(matched=False)


@router.get("/{name}/versions", response_model=list[PolicyVersionItem])
async def get_policy_versions(
    name: str,
    x_deliberate_api_key: str = Header(..., alias="X-Deliberate-API-Key"),
) -> list[PolicyVersionItem]:
    """Return version history for a policy, ordered by version DESC."""
    async with async_session() as session:
        await authenticate_api_key(x_deliberate_api_key, session, required_scope="policies:read")
        # Find the policy (active or inactive — history belongs to the record)
        result = await session.execute(select(PolicyRecord).where(PolicyRecord.name == name))
        record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(status_code=404, detail=f"Policy '{name}' not found")

    async with async_session() as session:
        versions_result = await session.execute(
            select(PolicyVersion)
            .where(PolicyVersion.policy_id == record.id)
            .order_by(PolicyVersion.version.desc())
        )
        versions = versions_result.scalars().all()

    return [
        PolicyVersionItem(
            version=v.version,
            content_hash=v.content_hash,
            changed_by=v.changed_by,
            change_reason=v.change_reason,
            created_at=v.created_at,
        )
        for v in versions
    ]
