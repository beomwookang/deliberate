"""Policy Pydantic models (PRD §5.2).

Defines the YAML policy schema, rule matching, approver specs,
and the ResolvedPlan returned by the policy engine.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from deliberate.types import ResolvedApprover


class Matcher(BaseModel):
    """Conditions for a policy to apply to an interrupt (PRD §5.2)."""

    layout: str | None = None
    subject_contains: str | None = None


class ApproverSpec(BaseModel):
    """Approver resolution specification in a policy rule (PRD §5.2).

    Exactly one of any_of or all_of should be set.
    """

    any_of: list[str] | None = None
    all_of: list[str] | None = None
    backup_delegate: str | None = None  # Schema-reserved, inert until v1.1


class Rule(BaseModel):
    """A single rule in a policy (PRD §5.2).

    Evaluation is top-to-bottom, first match wins.
    """

    name: str
    when: str  # Expression string evaluated by the parser
    action: Literal["auto_approve"] | None = None
    rationale: str | None = None  # Used when action == auto_approve
    approvers: ApproverSpec | None = None
    timeout: str | None = None  # e.g. "4h", "30m"
    on_timeout: Literal["escalate", "fail"] | None = None
    escalate_to: str | None = None
    require_rationale: bool = False
    notify: list[Literal["email", "webhook", "slack"]] = Field(default_factory=lambda: ["email"])


class Policy(BaseModel):
    """A complete policy loaded from a YAML file (PRD §5.2)."""

    name: str
    matches: Matcher
    rules: list[Rule]


class ResolvedPlan(BaseModel):
    """The output of policy evaluation — everything the server needs to route an interrupt."""

    action: Literal["auto_approve", "request_human"]
    matched_policy_name: str
    matched_rule_name: str
    policy_version_hash: str  # sha256 of policy file content

    # Only populated when action == "request_human":
    approvers: list[ResolvedApprover] = Field(default_factory=list)
    approval_mode: Literal["any_of", "all_of"] = "any_of"
    timeout_seconds: int | None = None
    notify_channels: list[Literal["email", "webhook", "slack"]] = Field(default_factory=list)
    require_rationale: bool = False

    # Fields reserved for M2b+:
    on_timeout: Literal["escalate", "fail"] | None = None
    escalate_to: str | None = None

    # Auto-approve fields:
    rationale: str | None = None


def parse_timeout(timeout_str: str) -> int:
    """Parse a timeout string like '4h', '30m', '1d' into seconds."""
    if not timeout_str:
        msg = "Empty timeout string"
        raise ValueError(msg)
    unit = timeout_str[-1].lower()
    try:
        value = int(timeout_str[:-1])
    except ValueError:
        msg = f"Invalid timeout value: {timeout_str}"
        raise ValueError(msg) from None
    if unit == "s":
        return value
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    if unit == "d":
        return value * 86400
    msg = f"Unknown timeout unit '{unit}' in '{timeout_str}'. Use s/m/h/d."
    raise ValueError(msg)
