"""The @approval_gate decorator for wrapping LangGraph nodes.

See PRD §6.2 and README Quickstart for usage:

    from deliberate import approval_gate

    @approval_gate(layout="financial_decision")
    def process_refund(state):
        return {
            "subject": "Refund for customer #4821",
            "amount": {"value": 750.00, "currency": "USD"},
            ...
        }

The decorated function returns a dict (the interrupt payload fields).
The decorator handles: submit to server, poll for decision, return decision.
For M1, polling blocks the graph execution thread — this is intentional.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable, Sequence
from functools import wraps
from typing import Any

from deliberate.client import DEFAULT_TIMEOUT_SECONDS, DeliberateClient
from deliberate.types import InterruptPayload

logger = logging.getLogger("deliberate.decorator")


def _ensure_config_in_signature(wrapper: Callable[..., Any], original: Callable[..., Any]) -> None:
    """Ensure the wrapper's __signature__ includes a 'config' parameter.

    LangGraph inspects the node function's signature to decide whether to pass
    config. If the user's function doesn't declare config, we inject it into the
    wrapper's signature so LangGraph always passes it transparently.
    """
    sig = inspect.signature(original)
    if "config" not in sig.parameters:
        params = list(sig.parameters.values())
        params.append(
            inspect.Parameter(
                "config",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
            )
        )
        wrapper.__signature__ = sig.replace(parameters=params)  # type: ignore[attr-defined]


def approval_gate(
    layout: str,
    notify: Sequence[str] | None = None,
    policy: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    server_url: str | None = None,
    api_key: str | None = None,
    ui_url: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that registers a LangGraph node as an approval gate.

    The decorated function should return a dict with interrupt payload fields
    (subject, amount, customer, agent_reasoning, evidence, etc.). The decorator
    wraps this in an InterruptPayload, submits to the Deliberate server, polls
    for a decision, and returns the decision as a state update.

    For M1, polling blocks the graph execution thread synchronously.

    Args:
        layout: Layout identifier (e.g. 'financial_decision').
        notify: Notification channels. Not used in M1.
        policy: YAML policy file path. Not used in M1.
        timeout_seconds: Client-side polling timeout. Default 1 hour.
        server_url: Override for DELIBERATE_SERVER_URL env var.
        api_key: Override for DELIBERATE_API_KEY env var.
        ui_url: Override for DELIBERATE_UI_URL env var.

    Returns:
        Decorated function with approval gate behavior.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract config — LangGraph passes it as kwarg when signature includes it
            config = kwargs.get("config")

            # Extract thread_id from config["configurable"]["thread_id"]
            thread_id: str | None = None
            if config is not None and isinstance(config, dict):
                configurable = config.get("configurable", {})
                if isinstance(configurable, dict):
                    thread_id = configurable.get("thread_id")

            if thread_id is None:
                raise RuntimeError(
                    "Could not resolve thread_id from LangGraph config. "
                    "Ensure the graph is invoked with a thread_id in the config, e.g.: "
                    "graph.invoke(state, config={'configurable': {'thread_id': '...'}})"
                )

            # Call the user's function to get the interrupt payload fields.
            # Pass config through only if the original function accepts it.
            sig = inspect.signature(func)
            if "config" in sig.parameters:
                result = func(*args, **kwargs)
            else:
                # Remove config from kwargs before calling original function
                call_kwargs = {k: v for k, v in kwargs.items() if k != "config"}
                result = func(*args, **call_kwargs)

            # Build InterruptPayload from the returned dict
            if isinstance(result, dict):
                payload_data = {"layout": layout, **result}
                payload = InterruptPayload(**payload_data)
            elif isinstance(result, InterruptPayload):
                payload = result
                if payload.layout != layout:
                    payload = payload.model_copy(update={"layout": layout})
            else:
                raise TypeError(
                    f"@approval_gate-decorated function must return a dict or "
                    f"InterruptPayload, got {type(result).__name__}"
                )

            # Submit to server, poll for decision, return result.
            # For M1, this blocks the graph thread synchronously.
            client = DeliberateClient(
                base_url=server_url,
                api_key=api_key,
                ui_url=ui_url,
            )

            loop = asyncio.new_event_loop()
            try:
                interrupt_result = loop.run_until_complete(
                    client.submit_interrupt(payload=payload, thread_id=thread_id)
                )

                # Auto-approve: return immediately
                if interrupt_result.status == "auto_approved":
                    return {
                        "decision": {
                            "decision_type": "auto_approve",
                            "decision_payload": None,
                            "rationale_category": "auto_approved_by_policy",
                            "rationale_notes": None,
                            "approval_id": str(interrupt_result.approval_group_id),
                            "approval_url": None,
                        }
                    }

                approval_id = interrupt_result.approval_id
                group_id = interrupt_result.approval_group_id
                use_group = interrupt_result.approval_mode == "all_of"

                url = client.approval_url(approval_id)
                logger.info("[APPROVAL_URL] %s", url)
                print(f"\n[DELIBERATE] Approval needed: {url}\n")

                decision_start = time.monotonic()

                decision = loop.run_until_complete(
                    client.wait_for_decision(
                        approval_id_or_group_id=group_id if use_group else approval_id,
                        timeout_seconds=timeout_seconds,
                        use_group=use_group,
                    )
                )

                resume_latency_ms = int((time.monotonic() - decision_start) * 1000)

                loop.run_until_complete(
                    client.submit_resume_ack(
                        approval_id=approval_id,
                        resume_status="success",
                        resume_latency_ms=resume_latency_ms,
                    )
                )

                return {
                    "decision": {
                        "decision_type": decision.decision_type,
                        "decision_payload": decision.decision_payload,
                        "rationale_category": decision.rationale_category,
                        "rationale_notes": decision.rationale_notes,
                        "approval_id": str(approval_id),
                        "approval_group_id": str(group_id),
                        "approval_url": url,
                    }
                }
            finally:
                loop.run_until_complete(client.close())
                loop.close()

        # Inject config into the wrapper's signature for LangGraph
        _ensure_config_in_signature(wrapper, func)

        wrapper._deliberate_gate = {  # type: ignore[attr-defined]
            "layout": layout,
            "notify": notify,
            "policy": policy,
            "timeout_seconds": timeout_seconds,
        }
        return wrapper

    return decorator
