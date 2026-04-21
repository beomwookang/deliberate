"""Reference LangGraph agent demonstrating the Deliberate SDK.

A minimal refund-processing agent with three nodes:
  1. classify — populates reasoning and evidence
  2. approve_refund — decorated with @approval_gate, waits for human decision
  3. process_refund — executes refund if approved

See PRD §3.2 Scenario A.

Usage:
    # Start the Deliberate stack first:
    #   cd <repo-root> && docker compose up -d
    #
    # Then run this agent:
    #   cd examples/refund_agent
    #   pip install -e . -e ../../sdk
    #   python agent.py
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from deliberate import approval_gate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("refund_agent")


class RefundState(TypedDict):
    customer_id: str
    customer_name: str
    amount: float
    currency: str
    reasoning: str
    evidence: list[dict[str, Any]]
    decision: dict[str, Any] | None


# --- Node 1: Classify the refund request ---


def classify(state: RefundState) -> dict[str, Any]:
    """Populate reasoning and evidence. In a real agent, this would call an LLM."""
    logger.info("Classifying refund request for customer %s", state["customer_id"])
    return {
        "reasoning": {
            "summary": "Refund justified by confirmed product issue and strong customer history.",
            "points": [
                f"Customer {state['customer_name']} reported persistent dashboard loading issues for 3 weeks",
                "Engineering confirmed the bug in tickets #4821 and #4856",
                f"Customer requests refund of ${state['amount']:.2f} {state['currency']}",
                "No prior refund requests in 18-month tenure",
            ],
            "confidence": "high",
        },
        "evidence": [
            {
                "type": "ticket",
                "id": "#4821",
                "summary": "Bug confirmed by engineering",
                "url": "https://support.example.com/tickets/4821",
            },
            {
                "type": "ticket",
                "id": "#4856",
                "summary": "Escalation — customer requesting refund",
                "url": "https://support.example.com/tickets/4856",
            },
            {
                "type": "history",
                "id": None,
                "summary": "No prior refunds in 18 months",
                "url": None,
            },
        ],
    }


# --- Node 2: Approval gate ---


@approval_gate(layout="financial_decision")
def approve_refund(state: RefundState) -> dict[str, Any]:
    """Submit the refund for human approval via Deliberate.

    Returns the interrupt payload fields. The @approval_gate decorator
    handles submission to the server, polling, and returning the decision.
    """
    return {
        "subject": f"Refund for customer #{state['customer_id']}",
        "amount": {"value": state["amount"], "currency": state["currency"]},
        "customer": {
            "id": state["customer_id"],
            "display_name": state["customer_name"],
            "tenure": "18 months",
        },
        "agent_reasoning": state["reasoning"],
        "evidence": state["evidence"],
        "rationale_categories": ["product_issue", "retention", "policy_exception", "other"],
    }


# --- Node 3: Process the refund ---


def process_refund(state: RefundState) -> dict[str, Any]:
    """Execute the refund if approved. In a real agent, this would call a payment API."""
    decision = state.get("decision")
    if not decision:
        logger.warning("No decision found — skipping refund processing")
        return {}

    decision_type = decision.get("decision_type", "unknown")

    if decision_type in ("approve", "modify"):
        logger.info(
            "Refund APPROVED for customer %s — $%.2f %s (reason: %s)",
            state["customer_id"],
            state["amount"],
            state["currency"],
            decision.get("rationale_category", "not specified"),
        )
        print(
            f"\n{'='*60}\n"
            f"REFUND PROCESSED\n"
            f"  Customer: {state['customer_name']} ({state['customer_id']})\n"
            f"  Amount:   ${state['amount']:.2f} {state['currency']}\n"
            f"  Decision: {decision_type}\n"
            f"  Reason:   {decision.get('rationale_category', 'N/A')}\n"
            f"  Notes:    {decision.get('rationale_notes', 'N/A')}\n"
            f"{'='*60}\n"
        )
    elif decision_type == "reject":
        logger.info("Refund REJECTED for customer %s", state["customer_id"])
        print(f"\nRefund REJECTED for customer {state['customer_name']}.\n")
    elif decision_type == "escalate":
        logger.info("Refund ESCALATED for customer %s", state["customer_id"])
        print(f"\nRefund ESCALATED — more info requested for {state['customer_name']}.\n")

    return {}


# --- Routing ---


def should_process(state: RefundState) -> str:
    """Route based on whether approval returned a decision."""
    if state.get("decision"):
        return "process_refund"
    return END


# --- Build the graph ---


def build_graph() -> StateGraph:
    graph = StateGraph(RefundState)

    graph.add_node("classify", classify)
    graph.add_node("approve_refund", approve_refund)
    graph.add_node("process_refund", process_refund)

    graph.set_entry_point("classify")
    graph.add_edge("classify", "approve_refund")
    graph.add_conditional_edges("approve_refund", should_process)
    graph.add_edge("process_refund", END)

    return graph


def main() -> None:
    """Run the example agent end-to-end."""
    print("\n" + "=" * 60)
    print("Deliberate Refund Agent — Example")
    print("=" * 60 + "\n")

    graph = build_graph()
    app = graph.compile()

    # Initial state
    initial_state: RefundState = {
        "customer_id": "cust_4821",
        "customer_name": "Maya Chen",
        "amount": 750.00,
        "currency": "USD",
        "reasoning": "",
        "evidence": [],
        "decision": None,
    }

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(f"Thread ID: {thread_id}")
    print(f"Customer:  {initial_state['customer_name']} ({initial_state['customer_id']})")
    print(f"Amount:    ${initial_state['amount']:.2f} {initial_state['currency']}")
    print()
    print("Starting agent... (will block at approval gate until human decides)")
    print()

    result = app.invoke(initial_state, config=config)

    print("\nAgent completed.")
    if result.get("decision"):
        print(f"Final decision: {result['decision'].get('decision_type', 'unknown')}")


if __name__ == "__main__":
    main()
