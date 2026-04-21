"""YAML policy engine (PRD §5.2, §6.2).

Loads policies from a directory, evaluates against incoming interrupt payloads,
and returns a ResolvedPlan with approvers, channels, timeout, and escalation.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from deliberate.types import ResolvedApprover
from pydantic import ValidationError

from deliberate_server.policy.directory import ApproverDirectory, ApproverNotFoundError
from deliberate_server.policy.evaluator import evaluate
from deliberate_server.policy.parser import ParseError, parse_expression
from deliberate_server.policy.types import (
    Matcher,
    Policy,
    ResolvedPlan,
    Rule,
    parse_timeout,
)

logger = logging.getLogger("deliberate_server.policy.engine")


class PolicyLoadError(Exception):
    """Raised when a policy file can't be loaded."""


class PolicyEvaluationError(Exception):
    """Raised when policy evaluation encounters a fatal error."""


class NoMatchingPolicyError(PolicyEvaluationError):
    """Raised when no policy matches the interrupt payload."""


class _LoadedPolicy:
    """A policy with its parsed expressions pre-compiled."""

    def __init__(self, policy: Policy, file_hash: str, file_path: str) -> None:
        self.policy = policy
        self.file_hash = file_hash
        self.file_path = file_path
        # Pre-parse all rule expressions to fail early on load
        self.compiled_rules: list[tuple[Rule, Any]] = []
        for rule in policy.rules:
            try:
                ast = parse_expression(rule.when)
            except (ParseError, Exception) as e:
                msg = (
                    f"Invalid expression in policy '{policy.name}', "
                    f"rule '{rule.name}': {rule.when!r} — {e}"
                )
                raise PolicyLoadError(msg) from e
            self.compiled_rules.append((rule, ast))


class PolicyEngine:
    """Evaluates YAML policies against interrupt payloads.

    Loads policies from a directory (hot-reloaded). On each incoming interrupt,
    evaluates rules top-to-bottom against the payload. Returns a resolved plan:
    approvers, channels, timeout, escalation target.
    """

    def __init__(self, directory: ApproverDirectory) -> None:
        self._directory = directory
        self._policies: list[_LoadedPolicy] = []
        self._policy_dir: Path | None = None
        self._file_hashes: dict[str, str] = {}  # path -> hash for reload detection

    def load_policies(self, directory: str | Path) -> None:
        """Load all YAML policy files from the given directory.

        Raises PolicyLoadError on parse/validation failure.
        Pre-parses all expressions to catch errors at load time.
        """
        path = Path(directory)
        if not path.exists():
            msg = f"Policy directory not found: {path}"
            raise PolicyLoadError(msg)
        if not path.is_dir():
            msg = f"Policy path is not a directory: {path}"
            raise PolicyLoadError(msg)

        policies: list[_LoadedPolicy] = []
        file_hashes: dict[str, str] = {}

        yaml_files = sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml"))
        if not yaml_files:
            logger.warning("No policy files found in %s", path)

        for fpath in yaml_files:
            content = fpath.read_text(encoding="utf-8")
            file_hash = hashlib.sha256(content.encode()).hexdigest()
            file_hashes[str(fpath)] = file_hash

            try:
                raw = yaml.safe_load(content)
            except yaml.YAMLError as e:
                msg = f"Invalid YAML in policy file {fpath}: {e}"
                raise PolicyLoadError(msg) from e

            if not isinstance(raw, dict):
                msg = f"Policy file must be a YAML mapping, got {type(raw).__name__} in {fpath}"
                raise PolicyLoadError(msg) from None

            try:
                policy = Policy(**raw)
            except ValidationError as e:
                msg = f"Invalid policy schema in {fpath}: {e}"
                raise PolicyLoadError(msg) from e

            # Validate approver references at load time
            for rule in policy.rules:
                if rule.approvers:
                    refs = rule.approvers.any_of or rule.approvers.all_of or []
                    for ref in refs:
                        try:
                            self._directory.resolve(ref)
                        except ApproverNotFoundError as e:
                            msg = (
                                f"Policy '{policy.name}', rule '{rule.name}' references "
                                f"unknown approver/group '{ref}': {e}"
                            )
                            raise PolicyLoadError(msg) from e

            loaded = _LoadedPolicy(policy, file_hash, str(fpath))
            policies.append(loaded)

        self._policies = policies
        self._policy_dir = path
        self._file_hashes = file_hashes

        logger.info("Loaded %d policies from %s", len(policies), path)

    def reload(self) -> bool:
        """Reload policies if any files changed.

        On error, keeps current policies and logs a warning.
        Returns True if policies were reloaded.
        """
        if self._policy_dir is None:
            return False

        # Quick check: any file changed?
        changed = False
        yaml_files = sorted(self._policy_dir.glob("*.yaml")) + sorted(
            self._policy_dir.glob("*.yml")
        )
        current_paths = {str(f) for f in yaml_files}
        old_paths = set(self._file_hashes.keys())

        if current_paths != old_paths:
            changed = True
        else:
            for fpath in yaml_files:
                content = fpath.read_text(encoding="utf-8")
                h = hashlib.sha256(content.encode()).hexdigest()
                if self._file_hashes.get(str(fpath)) != h:
                    changed = True
                    break

        if not changed:
            return False

        try:
            self.load_policies(self._policy_dir)
            logger.info("Hot-reloaded policies from %s", self._policy_dir)
            return True
        except PolicyLoadError as e:
            logger.warning("Failed to hot-reload policies (keeping current state): %s", e)
            return False

    def evaluate(self, payload: dict[str, Any]) -> ResolvedPlan:
        """Evaluate loaded policies against an interrupt payload.

        Returns a ResolvedPlan describing the action, approvers, and channels.
        Raises NoMatchingPolicyError if no policy matches.
        """
        layout = payload.get("layout", "")
        subject = payload.get("subject", "")

        for loaded in self._policies:
            policy = loaded.policy

            # Check matches block
            if not self._matches(policy.matches, layout, subject):
                continue

            # Evaluate rules top-to-bottom, first match wins
            for rule, ast in loaded.compiled_rules:
                try:
                    result = evaluate(ast, payload)
                except Exception:
                    logger.warning(
                        "Expression evaluation error in policy '%s', rule '%s' — skipping",
                        policy.name,
                        rule.name,
                        exc_info=True,
                    )
                    continue

                if not result:
                    continue

                # Rule matched — build the resolved plan
                return self._build_plan(rule, policy.name, loaded.file_hash)

        raise NoMatchingPolicyError(
            f"No policy matched interrupt with layout={layout!r}, subject={subject!r}"
        )

    def _matches(self, matcher: Matcher, layout: str, subject: str) -> bool:
        """Check if the interrupt matches the policy's matcher block."""
        if matcher.layout is not None and matcher.layout != layout:
            return False
        return not (
            matcher.subject_contains is not None and matcher.subject_contains not in subject
        )

    def _build_plan(self, rule: Rule, policy_name: str, file_hash: str) -> ResolvedPlan:
        """Build a ResolvedPlan from a matched rule."""
        if rule.action == "auto_approve":
            return ResolvedPlan(
                action="auto_approve",
                matched_policy_name=policy_name,
                matched_rule_name=rule.name,
                policy_version_hash=file_hash,
                rationale=rule.rationale,
            )

        # Human approval required
        approvers: list[ResolvedApprover] = []
        approval_mode: Literal["any_of", "all_of"] = "any_of"

        if rule.approvers:
            if rule.approvers.any_of:
                approval_mode = "any_of"
                for ref in rule.approvers.any_of:
                    approvers.extend(self._directory.resolve(ref))
            elif rule.approvers.all_of:
                approval_mode = "all_of"
                for ref in rule.approvers.all_of:
                    approvers.extend(self._directory.resolve(ref))

        timeout_seconds: int | None = None
        if rule.timeout:
            timeout_seconds = parse_timeout(rule.timeout)

        return ResolvedPlan(
            action="request_human",
            matched_policy_name=policy_name,
            matched_rule_name=rule.name,
            policy_version_hash=file_hash,
            approvers=approvers,
            approval_mode=approval_mode,
            timeout_seconds=timeout_seconds,
            notify_channels=rule.notify,
            require_rationale=rule.require_rationale,
            on_timeout=rule.on_timeout,
            escalate_to=rule.escalate_to,
        )

    @property
    def policy_count(self) -> int:
        return len(self._policies)

    @property
    def policy_names(self) -> list[str]:
        return [p.policy.name for p in self._policies]
