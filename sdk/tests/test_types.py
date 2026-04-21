"""Validate that SDK type models are importable and constructable."""

from deliberate.types import (
    AgentReasoningStructured,
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


def test_agent_reasoning_string() -> None:
    """String reasoning still works (backward compat)."""
    payload = InterruptPayload(
        layout="financial_decision",
        subject="Test",
        agent_reasoning="Simple string reasoning.",
    )
    assert payload.agent_reasoning == "Simple string reasoning."


def test_agent_reasoning_structured() -> None:
    """Structured reasoning with summary, points, confidence."""
    structured = AgentReasoningStructured(
        summary="Refund supported by product issue.",
        points=[
            "Customer reported issues for 3 weeks",
            "Engineering confirmed the bug",
        ],
        confidence="high",
    )
    payload = InterruptPayload(
        layout="financial_decision",
        subject="Test",
        agent_reasoning=structured,
    )
    assert isinstance(payload.agent_reasoning, AgentReasoningStructured)
    assert payload.agent_reasoning.summary == "Refund supported by product issue."
    assert len(payload.agent_reasoning.points or []) == 2
    assert payload.agent_reasoning.confidence == "high"


def test_agent_reasoning_structured_from_dict() -> None:
    """Structured reasoning can be passed as a raw dict."""
    payload = InterruptPayload(
        layout="financial_decision",
        subject="Test",
        agent_reasoning={
            "summary": "Short summary.",
            "points": ["Point 1", "Point 2"],
        },
    )
    assert isinstance(payload.agent_reasoning, AgentReasoningStructured)
    assert payload.agent_reasoning.confidence is None


def test_agent_reasoning_none() -> None:
    """None reasoning still works."""
    payload = InterruptPayload(layout="test", subject="Test", agent_reasoning=None)
    assert payload.agent_reasoning is None
