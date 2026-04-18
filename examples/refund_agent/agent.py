"""Reference LangGraph agent demonstrating the Deliberate SDK.

This is a minimal refund-processing agent with one node that uses
@approval_gate to pause for human approval. See PRD §3.2 Scenario A.

Running this will raise NotImplementedError because the SDK is a stub.
The structure is what matters for now.

Usage:
    python agent.py
"""

from __future__ import annotations

from typing import Any, TypedDict

from deliberate import approval_gate


class RefundState(TypedDict):
    customer_id: str
    customer_name: str
    amount: float
    currency: str
    reasoning: str
    evidence: list[dict[str, Any]]
    decision: dict[str, Any] | None


@approval_gate(
    layout="financial_decision",
    notify=["email:finance@acme.com", "slack:#finance-approvals"],
    policy="policies/refund.yaml",
)
def process_refund(state: RefundState) -> dict[str, Any]:
    """Node that submits a refund for human approval.

    In a real agent, this would call interrupt() with the payload.
    The @approval_gate decorator intercepts it, routes through Deliberate,
    and returns the approver's decision.
    """
    # This would normally be: return interrupt({...})
    # But since the SDK is a stub, the decorator raises NotImplementedError.
    return {
        "subject": f"Refund for customer #{state['customer_id']}",
        "amount": {"value": state["amount"], "currency": state["currency"]},
        "customer": {
            "id": state["customer_id"],
            "display_name": state["customer_name"],
        },
        "agent_reasoning": state["reasoning"],
        "evidence": state["evidence"],
    }


def main() -> None:
    """Run the example agent. Will raise NotImplementedError from the stub SDK."""
    sample_state: RefundState = {
        "customer_id": "cust_4821",
        "customer_name": "Maya Chen",
        "amount": 750.00,
        "currency": "USD",
        "reasoning": "Customer reported persistent dashboard loading issues for 3 weeks.",
        "evidence": [
            {"type": "ticket", "id": "#4821", "summary": "Bug confirmed"},
            {"type": "history", "summary": "No prior refunds"},
        ],
        "decision": None,
    }

    try:
        result = process_refund(sample_state)
        print(f"Decision: {result}")
    except NotImplementedError as e:
        print(f"Expected: {e}")
        print("The SDK is a stub — this will work once M1 ships.")


if __name__ == "__main__":
    main()
