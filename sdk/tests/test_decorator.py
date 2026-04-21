"""Tests for the @approval_gate decorator.

Tests use a mocked DeliberateClient to avoid network calls.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from deliberate.client import InterruptResult
from deliberate.decorator import approval_gate
from deliberate.types import Decision, DeliberateTimeoutError

FAKE_APPROVAL_ID = uuid4()
FAKE_GROUP_ID = uuid4()
FAKE_DECISION = Decision(
    id=FAKE_APPROVAL_ID,
    decision_type="approve",
    decision_payload={"amount": 750.0},
    rationale_category="product_issue",
    rationale_notes="Bug confirmed",
)


def _mock_client() -> Any:
    """Create a mock DeliberateClient that returns a successful decision."""
    mock = AsyncMock()
    mock.submit_interrupt.return_value = InterruptResult(
        approval_group_id=FAKE_GROUP_ID,
        approval_ids=[FAKE_APPROVAL_ID],
        approval_mode="any_of",
        status="pending",
    )
    mock.approval_url.return_value = f"http://localhost:3000/a/{FAKE_APPROVAL_ID}"
    mock.wait_for_decision.return_value = FAKE_DECISION
    mock.submit_resume_ack.return_value = None
    mock.close.return_value = None
    return mock


class TestApprovalGateMetadata:
    def test_creates_decorator_with_metadata(self) -> None:
        @approval_gate(layout="financial_decision", notify=["slack:#test"], policy="test.yaml")
        def my_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"subject": "Test"}

        assert hasattr(my_node, "_deliberate_gate")
        assert my_node._deliberate_gate["layout"] == "financial_decision"
        assert my_node._deliberate_gate["notify"] == ["slack:#test"]

    def test_injects_config_into_signature(self) -> None:
        """Decorator should add config param to signature if not present."""

        @approval_gate(layout="financial_decision")
        def my_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"subject": "Test"}

        sig = inspect.signature(my_node)
        assert "config" in sig.parameters

    def test_preserves_existing_config_param(self) -> None:
        """If function already has config, don't add a duplicate."""

        @approval_gate(layout="financial_decision")
        def my_node(state: dict[str, Any], *, config: Any = None) -> dict[str, Any]:
            return {"subject": "Test"}

        sig = inspect.signature(my_node)
        params = list(sig.parameters.keys())
        assert params.count("config") == 1


class TestApprovalGateExecution:
    def test_raises_without_thread_id(self) -> None:
        @approval_gate(layout="financial_decision")
        def my_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"subject": "Test"}

        with pytest.raises(RuntimeError, match="thread_id"):
            my_node({"key": "val"}, config={})

    def test_raises_with_none_config(self) -> None:
        @approval_gate(layout="financial_decision")
        def my_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"subject": "Test"}

        with pytest.raises(RuntimeError, match="thread_id"):
            my_node({"key": "val"}, config=None)

    @patch("deliberate.decorator.DeliberateClient")
    def test_happy_path(self, mock_client_cls: Any) -> None:
        """Full flow: submit → poll → decision → resume ACK."""
        mock = _mock_client()
        mock_client_cls.return_value = mock

        @approval_gate(layout="financial_decision")
        def my_node(state: dict[str, Any]) -> dict[str, Any]:
            return {
                "subject": f"Refund for {state['customer']}",
                "amount": {"value": 750.0, "currency": "USD"},
            }

        config = {"configurable": {"thread_id": "thread-123"}}
        result = my_node({"customer": "Maya Chen"}, config=config)

        assert result["decision"]["decision_type"] == "approve"
        assert result["decision"]["decision_payload"] == {"amount": 750.0}
        assert result["decision"]["approval_id"] == str(FAKE_APPROVAL_ID)
        mock.submit_interrupt.assert_called_once()
        mock.wait_for_decision.assert_called_once()
        mock.submit_resume_ack.assert_called_once()

    @patch("deliberate.decorator.DeliberateClient")
    def test_passes_config_to_original_if_declared(self, mock_client_cls: Any) -> None:
        """If the user's function declares config, it receives it."""
        mock = _mock_client()
        mock_client_cls.return_value = mock
        received_config: dict[str, Any] = {}

        @approval_gate(layout="financial_decision")
        def my_node(state: dict[str, Any], *, config: Any = None) -> dict[str, Any]:
            received_config.update(config or {})
            return {"subject": "Test"}

        config = {"configurable": {"thread_id": "thread-123"}}
        my_node({"key": "val"}, config=config)
        assert received_config == config

    @patch("deliberate.decorator.DeliberateClient")
    def test_does_not_pass_config_if_not_declared(self, mock_client_cls: Any) -> None:
        """If the user's function doesn't declare config, don't pass it."""
        mock = _mock_client()
        mock_client_cls.return_value = mock

        @approval_gate(layout="financial_decision")
        def my_node(state: dict[str, Any]) -> dict[str, Any]:
            # This would fail if config was passed as unexpected kwarg
            return {"subject": "Test"}

        config = {"configurable": {"thread_id": "thread-123"}}
        result = my_node({"key": "val"}, config=config)
        assert result["decision"]["decision_type"] == "approve"

    @patch("deliberate.decorator.DeliberateClient")
    def test_timeout_raises_deliberate_timeout_error(self, mock_client_cls: Any) -> None:
        mock = _mock_client()
        mock.wait_for_decision.side_effect = DeliberateTimeoutError(str(FAKE_APPROVAL_ID), 10)
        mock_client_cls.return_value = mock

        @approval_gate(layout="financial_decision", timeout_seconds=10)
        def my_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"subject": "Test"}

        config = {"configurable": {"thread_id": "thread-123"}}
        with pytest.raises(DeliberateTimeoutError):
            my_node({"key": "val"}, config=config)

    @patch("deliberate.decorator.DeliberateClient")
    def test_accepts_interrupt_payload_directly(self, mock_client_cls: Any) -> None:
        """Function can return an InterruptPayload instance."""
        from deliberate.types import InterruptPayload

        mock = _mock_client()
        mock_client_cls.return_value = mock

        @approval_gate(layout="financial_decision")
        def my_node(state: dict[str, Any]) -> InterruptPayload:
            return InterruptPayload(layout="financial_decision", subject="Test direct")

        config = {"configurable": {"thread_id": "thread-123"}}
        result = my_node({"key": "val"}, config=config)
        assert result["decision"]["decision_type"] == "approve"

    @patch("deliberate.decorator.DeliberateClient")
    def test_rejects_non_dict_return(self, mock_client_cls: Any) -> None:
        mock = _mock_client()
        mock_client_cls.return_value = mock

        @approval_gate(layout="financial_decision")
        def my_node(state: dict[str, Any]) -> str:
            return "not a dict"  # type: ignore[return-value]

        config = {"configurable": {"thread_id": "thread-123"}}
        with pytest.raises(TypeError, match="must return a dict"):
            my_node({"key": "val"}, config=config)
