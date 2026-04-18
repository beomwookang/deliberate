"""Validate that the @approval_gate decorator is importable and callable."""

import pytest

from deliberate.decorator import approval_gate


def test_approval_gate_creates_decorator() -> None:
    @approval_gate(layout="financial_decision", notify=["slack:#test"], policy="test.yaml")
    def my_node(state: dict) -> dict:
        return state

    assert hasattr(my_node, "_deliberate_gate")
    assert my_node._deliberate_gate["layout"] == "financial_decision"


def test_approval_gate_stub_raises() -> None:
    @approval_gate(layout="document_review")
    def my_node(state: dict) -> dict:
        return state

    with pytest.raises(NotImplementedError, match="stub"):
        my_node({})
