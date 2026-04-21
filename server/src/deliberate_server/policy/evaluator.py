"""Evaluate a parsed expression AST against an interrupt payload.

Key semantic: missing field access evaluates to a sentinel _MISSING value,
and any comparison involving _MISSING produces False (not an error).
This allows policies to work across payload variants (PRD §5.2 Draft v4).

The `contains` operator on structured agent_reasoning objects falls back
to the `summary` field.
"""

from __future__ import annotations

import logging
from typing import Any

from deliberate_server.policy.parser import (
    AndOp,
    ASTNode,
    BinOp,
    BoolLit,
    ContainsOp,
    FieldAccess,
    NotOp,
    NullLit,
    NumberLit,
    OrOp,
    StringLit,
)

logger = logging.getLogger("deliberate_server.policy.evaluator")


class _Missing:
    """Sentinel for unresolved field access — never equal to anything."""

    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


class EvaluationError(Exception):
    """Raised on type errors that can't be silently handled."""


def _resolve_field(payload: dict[str, Any], parts: list[str]) -> Any:
    """Walk dotted path through nested dicts/objects.

    Returns MISSING if any segment doesn't resolve (instead of raising).
    """
    current: Any = payload
    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                return MISSING
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return MISSING
    return current


def _is_missing(val: Any) -> bool:
    return isinstance(val, _Missing)


def _coerce_for_contains(value: Any) -> str | None:
    """Extract string for `contains` operator.

    For structured agent_reasoning objects (dicts with a 'summary' key),
    falls back to the summary field per PRD §5.2 Draft v4.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "summary" in value:
        s = value["summary"]
        return str(s) if not isinstance(s, str) else s
    return None


def evaluate(node: ASTNode, payload: dict[str, Any]) -> Any:
    """Evaluate an AST node against a payload dict.

    Returns the result value. For boolean expressions, returns True/False.
    For comparisons involving MISSING fields, returns False.
    """
    if isinstance(node, NumberLit):
        return node.value

    if isinstance(node, StringLit):
        return node.value

    if isinstance(node, BoolLit):
        return node.value

    if isinstance(node, NullLit):
        return None

    if isinstance(node, FieldAccess):
        return _resolve_field(payload, node.parts)

    if isinstance(node, BinOp):
        left = evaluate(node.left, payload)
        right = evaluate(node.right, payload)

        # Any comparison with MISSING → False
        if _is_missing(left) or _is_missing(right):
            return False

        op = node.op
        try:
            if op == "<":
                return left < right  # type: ignore[operator]
            if op == ">":
                return left > right  # type: ignore[operator]
            if op == "<=":
                return left <= right  # type: ignore[operator]
            if op == ">=":
                return left >= right  # type: ignore[operator]
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
        except TypeError:
            # Type mismatch in comparison (e.g., str < int) → False
            return False

        msg = f"Unknown operator: {op}"
        raise EvaluationError(msg)

    if isinstance(node, ContainsOp):
        left = evaluate(node.left, payload)
        right = evaluate(node.right, payload)

        if _is_missing(left) or _is_missing(right):
            return False

        # Try string contains with structured-object fallback
        left_str = _coerce_for_contains(left)
        if left_str is not None and isinstance(right, str):
            return right in left_str

        # List membership
        if isinstance(left, list):
            return right in left

        return False

    if isinstance(node, AndOp):
        left = evaluate(node.left, payload)
        if _is_missing(left) or not left:
            return False
        right = evaluate(node.right, payload)
        if _is_missing(right):
            return False
        return bool(right)

    if isinstance(node, OrOp):
        left = evaluate(node.left, payload)
        if not _is_missing(left) and left:
            return True
        right = evaluate(node.right, payload)
        if _is_missing(right):
            return False
        return bool(right)

    if isinstance(node, NotOp):
        val = evaluate(node.operand, payload)
        if _is_missing(val):
            return True  # not(missing) → True (missing is falsy)
        return not val

    msg = f"Unknown AST node type: {type(node).__name__}"
    raise EvaluationError(msg)
