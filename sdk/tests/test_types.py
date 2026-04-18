"""Validate that SDK type models are importable and constructable."""

from deliberate.types import (
    Decision,
    DecisionOption,
    Evidence,
    InterruptPayload,
    MoneyAmount,
)


def test_interrupt_payload_minimal() -> None:
    payload = InterruptPayload(layout="financial_decision", subject="Test refund")
    assert payload.layout == "financial_decision"
    assert payload.subject == "Test refund"


def test_interrupt_payload_full() -> None:
    payload = InterruptPayload(
        layout="financial_decision",
        subject="Refund for customer #4821",
        amount=MoneyAmount(value=750.00, currency="USD"),
        customer={"id": "cust_4821", "display_name": "Maya Chen"},
        agent_reasoning="Bug confirmed by engineering.",
        evidence=[Evidence(type="ticket", id="#4821", summary="Bug confirmed")],
        decision_options=[
            DecisionOption(type="approve", label="Approve as-is"),
            DecisionOption(type="reject", label="Reject"),
        ],
        rationale_categories=["product_issue", "retention"],
        metadata={"thread_id": "thread-123"},
    )
    assert payload.amount is not None
    assert payload.amount.value == 750.00
    assert len(payload.evidence or []) == 1


def test_decision_model() -> None:
    from uuid import uuid4

    d = Decision(id=uuid4(), decision_type="approve")
    assert d.decision_type == "approve"
