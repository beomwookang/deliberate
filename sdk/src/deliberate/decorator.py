"""The @approval_gate decorator for wrapping LangGraph nodes.

See PRD §6.2 and README Quickstart for usage:

    from deliberate import approval_gate
    from langgraph.types import interrupt

    @approval_gate(
        layout="financial_decision",
        notify=["email:finance@acme.com", "slack:#finance-approvals"],
        policy="policies/refund.yaml",
    )
    def process_refund(state):
        return interrupt({...})
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import wraps
from typing import Any


def approval_gate(
    layout: str,
    notify: Sequence[str] | None = None,
    policy: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that registers a LangGraph node as an approval gate.

    When the decorated node calls interrupt(), the SDK intercepts the payload,
    sends it to the Deliberate server for routing and notification, and waits
    for the approver's decision before resuming the graph.

    Args:
        layout: Layout identifier (e.g. 'financial_decision', 'document_review').
        notify: Notification channels (e.g. ['email:user@co.com', 'slack:#channel']).
        policy: Path to the YAML policy file for routing this interrupt.

    Returns:
        Decorated function with approval gate behavior.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError(
                "approval_gate is a stub — full implementation ships in M1. "
                f"layout={layout!r}, notify={notify!r}, policy={policy!r}"
            )

        wrapper._deliberate_gate = {  # type: ignore[attr-defined]
            "layout": layout,
            "notify": notify,
            "policy": policy,
        }
        return wrapper

    return decorator
