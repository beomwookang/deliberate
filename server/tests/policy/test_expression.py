"""Tests for the expression parser and evaluator (Phase 1.2).

Covers all operators, boolean logic, union-type handling, and edge cases.
Target: 30+ test cases per the quality bar.
"""

from __future__ import annotations

import pytest

from deliberate_server.policy.evaluator import MISSING, evaluate
from deliberate_server.policy.parser import ParseError, TokenizeError, parse_expression


# ---------------------------------------------------------------------------
# Helper: parse + evaluate in one step
# ---------------------------------------------------------------------------

def _eval(expr: str, payload: dict) -> object:
    ast = parse_expression(expr)
    return evaluate(ast, payload)


# ---------------------------------------------------------------------------
# Comparison operators
# ---------------------------------------------------------------------------

class TestComparisonOperators:
    PAYLOAD = {"amount": {"value": 750.0, "currency": "USD"}, "count": 5}

    def test_less_than_true(self) -> None:
        assert _eval("amount.value < 1000", self.PAYLOAD) is True

    def test_less_than_false(self) -> None:
        assert _eval("amount.value < 500", self.PAYLOAD) is False

    def test_greater_than_true(self) -> None:
        assert _eval("amount.value > 500", self.PAYLOAD) is True

    def test_greater_than_false(self) -> None:
        assert _eval("amount.value > 1000", self.PAYLOAD) is False

    def test_less_equal_true(self) -> None:
        assert _eval("amount.value <= 750", self.PAYLOAD) is True

    def test_less_equal_boundary(self) -> None:
        assert _eval("amount.value <= 750.0", self.PAYLOAD) is True

    def test_greater_equal_true(self) -> None:
        assert _eval("amount.value >= 750", self.PAYLOAD) is True

    def test_greater_equal_false(self) -> None:
        assert _eval("amount.value >= 1000", self.PAYLOAD) is False

    def test_equal_number(self) -> None:
        assert _eval("count == 5", self.PAYLOAD) is True

    def test_equal_string(self) -> None:
        assert _eval("amount.currency == 'USD'", self.PAYLOAD) is True

    def test_not_equal(self) -> None:
        assert _eval("amount.currency != 'EUR'", self.PAYLOAD) is True

    def test_not_equal_false(self) -> None:
        assert _eval("amount.currency != 'USD'", self.PAYLOAD) is False

    def test_integer_comparison(self) -> None:
        assert _eval("count > 3", self.PAYLOAD) is True

    def test_double_quoted_string(self) -> None:
        assert _eval('amount.currency == "USD"', self.PAYLOAD) is True


# ---------------------------------------------------------------------------
# Boolean operators
# ---------------------------------------------------------------------------

class TestBooleanOperators:
    PAYLOAD = {"amount": {"value": 750.0}, "active": True, "deleted": False}

    def test_and_both_true(self) -> None:
        assert _eval("amount.value > 100 and amount.value < 1000", self.PAYLOAD) is True

    def test_and_one_false(self) -> None:
        assert _eval("amount.value > 100 and amount.value < 500", self.PAYLOAD) is False

    def test_or_first_true(self) -> None:
        assert _eval("amount.value < 100 or amount.value > 500", self.PAYLOAD) is True

    def test_or_both_false(self) -> None:
        assert _eval("amount.value < 100 or amount.value > 1000", self.PAYLOAD) is False

    def test_not_true(self) -> None:
        assert _eval("not deleted", self.PAYLOAD) is True

    def test_not_false(self) -> None:
        assert _eval("not active", self.PAYLOAD) is False

    def test_complex_boolean(self) -> None:
        assert _eval(
            "amount.value >= 100 and amount.value < 5000 and not deleted", self.PAYLOAD
        ) is True

    def test_parenthesized(self) -> None:
        assert _eval("(amount.value < 100) or (amount.value > 500)", self.PAYLOAD) is True

    def test_nested_parens(self) -> None:
        assert _eval(
            "(amount.value > 100 and amount.value < 1000) or deleted", self.PAYLOAD
        ) is True


# ---------------------------------------------------------------------------
# Contains operator
# ---------------------------------------------------------------------------

class TestContainsOperator:
    def test_string_contains_true(self) -> None:
        payload = {"agent_reasoning": "Customer reported fraud and billing issues"}
        assert _eval("agent_reasoning contains 'fraud'", payload) is True

    def test_string_contains_false(self) -> None:
        payload = {"agent_reasoning": "Normal refund request"}
        assert _eval("agent_reasoning contains 'fraud'", payload) is False

    def test_contains_double_quoted(self) -> None:
        payload = {"subject": "Refund for customer #4821"}
        assert _eval('subject contains "Refund"', payload) is True

    def test_list_contains(self) -> None:
        payload = {"tags": ["urgent", "finance", "refund"]}
        assert _eval("tags contains 'urgent'", payload) is True

    def test_list_contains_false(self) -> None:
        payload = {"tags": ["finance"]}
        assert _eval("tags contains 'urgent'", payload) is False


# ---------------------------------------------------------------------------
# Union-type handling (agent_reasoning as string vs structured object)
# Per Correction 3: missing field access → false, not error.
# ---------------------------------------------------------------------------

class TestUnionTypeHandling:
    """PRD §5.2 Draft v4: expression evaluator semantics for union types."""

    def test_dotted_access_on_string_returns_false(self) -> None:
        """when: 'agent_reasoning.confidence == low' with string reasoning → false."""
        payload = {"agent_reasoning": "Simple refund request"}
        assert _eval("agent_reasoning.confidence == 'low'", payload) is False

    def test_dotted_access_on_structured_works(self) -> None:
        """when: 'agent_reasoning.confidence == low' with structured reasoning → match."""
        payload = {
            "agent_reasoning": {
                "summary": "Refund supported by evidence",
                "points": ["Bug confirmed"],
                "confidence": "low",
            }
        }
        assert _eval("agent_reasoning.confidence == 'low'", payload) is True

    def test_contains_on_string_reasoning(self) -> None:
        """when: 'agent_reasoning contains fraud' with string → standard string contains."""
        payload = {"agent_reasoning": "Possible fraud detected in transaction"}
        assert _eval("agent_reasoning contains 'fraud'", payload) is True

    def test_contains_on_structured_falls_back_to_summary(self) -> None:
        """when: 'agent_reasoning contains fraud' with structured → checks summary."""
        payload = {
            "agent_reasoning": {
                "summary": "Possible fraud detected in transaction",
                "points": ["Transaction pattern unusual"],
                "confidence": "high",
            }
        }
        assert _eval("agent_reasoning contains 'fraud'", payload) is True

    def test_contains_on_structured_summary_no_match(self) -> None:
        payload = {
            "agent_reasoning": {
                "summary": "Normal refund request",
                "points": ["fraud mentioned only in points"],
            }
        }
        assert _eval("agent_reasoning contains 'fraud'", payload) is False

    def test_missing_field_entirely(self) -> None:
        """Dotted path that doesn't exist at all → false."""
        payload = {"amount": {"value": 100}}
        assert _eval("customer.tenure == '18 months'", payload) is False

    def test_deeply_nested_missing(self) -> None:
        payload = {"amount": {"value": 100}}
        assert _eval("customer.profile.tier == 'gold'", payload) is False

    def test_missing_in_and_short_circuits(self) -> None:
        """Missing field in AND → false (whole expression)."""
        payload = {"amount": {"value": 100}}
        assert _eval("amount.value > 50 and customer.tier == 'gold'", payload) is False

    def test_missing_in_or_fallback(self) -> None:
        """Missing field in OR → other branch can still match."""
        payload = {"amount": {"value": 100}}
        assert _eval("customer.tier == 'gold' or amount.value > 50", payload) is True

    def test_not_missing_is_true(self) -> None:
        """not(missing_field) → True (missing is falsy)."""
        payload = {"amount": {"value": 100}}
        assert _eval("not customer.is_blocked", payload) is True


# ---------------------------------------------------------------------------
# Literals and edge cases
# ---------------------------------------------------------------------------

class TestLiteralsAndEdgeCases:
    def test_true_literal(self) -> None:
        assert _eval("true", {}) is True

    def test_false_literal(self) -> None:
        assert _eval("false", {}) is False

    def test_null_comparison(self) -> None:
        payload = {"trace_id": None}
        assert _eval("trace_id == null", payload) is True

    def test_null_not_equal(self) -> None:
        payload = {"trace_id": "abc"}
        assert _eval("trace_id != null", payload) is True

    def test_negative_number(self) -> None:
        payload = {"balance": -50}
        assert _eval("balance < 0", payload) is True

    def test_float_number(self) -> None:
        payload = {"score": 3.14}
        assert _eval("score > 3.0", payload) is True

    def test_type_mismatch_comparison_returns_false(self) -> None:
        """Comparing string to number → False, not error."""
        payload = {"name": "Alice", "count": 5}
        assert _eval("name > 5", payload) is False

    def test_empty_payload(self) -> None:
        assert _eval("true", {}) is True

    def test_nested_field_access(self) -> None:
        payload = {"a": {"b": {"c": 42}}}
        assert _eval("a.b.c == 42", payload) is True


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------

class TestParseErrors:
    def test_empty_expression(self) -> None:
        with pytest.raises(ParseError):
            parse_expression("")

    def test_unclosed_paren(self) -> None:
        with pytest.raises(ParseError):
            parse_expression("(a > 5")

    def test_unexpected_token(self) -> None:
        with pytest.raises(ParseError):
            parse_expression("> 5")

    def test_tokenize_error(self) -> None:
        with pytest.raises(TokenizeError):
            parse_expression("a @ b")
