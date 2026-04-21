"""Adversarial tests for policy parser and evaluator (M2a Validation Part B).

B1: Parser must reject dangerous inputs (security-critical).
B2: Evaluator edge cases with concrete payloads.
B3: Policy matching edge cases.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from deliberate_server.policy.directory import ApproverDirectory
from deliberate_server.policy.engine import NoMatchingPolicyError, PolicyEngine, PolicyLoadError
from deliberate_server.policy.evaluator import evaluate
from deliberate_server.policy.parser import ParseError, TokenizeError, parse_expression


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _eval(expr: str, payload: dict) -> object:
    ast = parse_expression(expr)
    return evaluate(ast, payload)


# ---------------------------------------------------------------------------
# B1 — Parser rejects dangerous input
# ---------------------------------------------------------------------------

class TestB1ParserRejectsDangerous:
    """Each of these MUST raise ParseError or TokenizeError, never evaluate."""

    def test_python_import(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("__import__('os').system('rm -rf /')")

    def test_or_true_bareword(self) -> None:
        """'True' (capital T) is not our boolean 'true' — should it parse?"""
        # 'True' is parsed as an identifier (field access), not a boolean.
        # 'amount.value < 100 or True' parses as: (amount.value < 100) or (FieldAccess['True'])
        # This is NOT dangerous — it evaluates True as a field lookup which returns MISSING → false.
        # But let's verify it doesn't short-circuit to True.
        result = _eval("amount.value < 100 or True", {"amount": {"value": 200}})
        # True is parsed as field access "True" → MISSING → false
        # amount.value < 100 → false
        # false or false → false
        assert result is False

    def test_semicolon_statement_separator(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("amount.value; print(secret)")

    def test_js_arrow_function(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("() => true")

    def test_sql_injection(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("1 == 1 -- DROP TABLE users")

    def test_while_keyword(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("amount.value < 100 and (while true)")

    def test_template_strings(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("{{template}}")

    def test_hex_literal(self) -> None:
        """Hex literals are not in spec — should reject."""
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("amount.value < 0x100")

    def test_exponentiation_operator(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("amount.value ** 2 > 1")

    def test_python_in_operator(self) -> None:
        """'in' is not in our spec — parsed as identifier, causes parse error."""
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("amount.value in [100, 200]")

    def test_square_brackets(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("[1, 2, 3]")

    def test_curly_braces(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("{key: value}")

    def test_assignment(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("amount.value = 100")

    def test_lambda(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("lambda x: x > 5")

    def test_backtick_execution(self) -> None:
        with pytest.raises((ParseError, TokenizeError)):
            parse_expression("`rm -rf /`")


# ---------------------------------------------------------------------------
# B2 — Evaluator edge cases
# ---------------------------------------------------------------------------

class TestB2EvaluatorEdgeCases:
    def test_deeply_nested_field(self) -> None:
        payload = {"customer": {"metadata": {"tier": {"level": "gold"}}}}
        assert _eval('customer.metadata.tier.level == "gold"', payload) is True

    def test_field_on_null_returns_false(self) -> None:
        payload = {"customer": {"metadata": None}}
        assert _eval('customer.metadata.missing.deeper == "x"', payload) is False

    def test_field_on_missing_intermediate(self) -> None:
        payload = {"customer": {}}
        assert _eval('customer.metadata.missing.deeper == "x"', payload) is False

    def test_float_comparison(self) -> None:
        payload = {"amount": {"value": 100.0}}
        assert _eval("amount.value > 99.99", payload) is True

    def test_string_comparison_korean(self) -> None:
        payload = {"customer": {"region": "KR"}}
        assert _eval('customer.region == "KR"', payload) is True

    def test_boolean_field_true(self) -> None:
        payload = {"customer": {"verified": True}}
        assert _eval("customer.verified == true", payload) is True

    def test_boolean_field_false(self) -> None:
        payload = {"customer": {"verified": False}}
        assert _eval("customer.verified == false", payload) is True

    def test_contains_on_list(self) -> None:
        payload = {"tags": ["urgent", "finance", "refund"]}
        assert _eval("tags contains 'urgent'", payload) is True

    def test_contains_on_string_field(self) -> None:
        payload = {"customer": {"display_name": "premium_user_123"}}
        assert _eval("customer.display_name contains 'premium'", payload) is True

    def test_contains_structured_reasoning_uses_summary(self) -> None:
        payload = {
            "agent_reasoning": {
                "summary": "Possible fraud detected",
                "points": ["Pattern match"],
                "confidence": "high",
            }
        }
        assert _eval("agent_reasoning contains 'fraud'", payload) is True

    def test_contains_missing_field_returns_false(self) -> None:
        payload = {"amount": {"value": 100}}
        assert _eval("nonexistent contains 'test'", payload) is False

    def test_not_missing_is_true(self) -> None:
        """not(missing_field) → True per documented behavior."""
        payload = {"amount": {"value": 100}}
        assert _eval("not customer.verified", payload) is True

    def test_precedence_and_before_or(self) -> None:
        """'a == 1 and b == 2 or c == 3' should group as '(a==1 and b==2) or c==3'."""
        payload = {"a": 1, "b": 99, "c": 3}
        # (1==1 and 99==2) or 3==3 → (true and false) or true → false or true → true
        assert _eval("a == 1 and b == 2 or c == 3", payload) is True
        # Verify it's NOT: a==1 and (b==2 or c==3) → 1==1 and (false or true) → true and true → true
        # Both would be true for this payload; use a different payload
        payload2 = {"a": 99, "b": 2, "c": 3}
        # (99==1 and 2==2) or 3==3 → (false and true) or true → false or true → true
        # vs a==1 and (b==2 or c==3) → false and (true or true) → false and true → false
        assert _eval("a == 1 and b == 2 or c == 3", payload2) is True  # and-before-or

    def test_nested_parens(self) -> None:
        payload = {"a": 1, "b": 99, "c": 3, "d": 4}
        result = _eval("(a == 1 or b == 2) and (c == 3 or d == 5)", payload)
        # (true or false) and (true or false) → true and true → true
        assert result is True

        payload2 = {"a": 99, "b": 99, "c": 3, "d": 4}
        result2 = _eval("(a == 1 or b == 2) and (c == 3 or d == 5)", payload2)
        # (false or false) and (true or false) → false and true → false
        assert result2 is False

    def test_comparison_with_zero(self) -> None:
        payload = {"amount": {"value": 0}}
        assert _eval("amount.value == 0", payload) is True
        assert _eval("amount.value >= 0", payload) is True

    def test_negative_value(self) -> None:
        payload = {"balance": -50.5}
        assert _eval("balance < 0", payload) is True

    def test_empty_string_comparison(self) -> None:
        payload = {"name": ""}
        assert _eval("name == ''", payload) is True

    def test_contains_empty_string(self) -> None:
        payload = {"name": "Alice"}
        assert _eval("name contains ''", payload) is True  # "" in "Alice" is True in Python


# ---------------------------------------------------------------------------
# B3 — Policy matching edge cases
# ---------------------------------------------------------------------------

def _make_directory(tmp_path: Path) -> ApproverDirectory:
    content = textwrap.dedent("""\
        approvers:
          - id: alice
            email: alice@test.com
          - id: bob
            email: bob@test.com
        groups:
          - id: team
            members: [alice, bob]
    """)
    p = tmp_path / "approvers.yaml"
    p.write_text(content)
    d = ApproverDirectory()
    d.load(p)
    return d


class TestB3PolicyMatchingEdgeCases:
    def test_empty_policies_dir_no_env_raises(self, tmp_path: Path) -> None:
        d = _make_directory(tmp_path)
        engine = PolicyEngine(d)
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()
        engine.load_policies(policies_dir)

        with pytest.raises(NoMatchingPolicyError):
            engine.evaluate({"layout": "test", "subject": "Test"})

    def test_invalid_yaml_among_valid_fails_load(self, tmp_path: Path) -> None:
        """If one policy file is invalid YAML, the entire load fails."""
        d = _make_directory(tmp_path)
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()

        (policies_dir / "good.yaml").write_text(textwrap.dedent("""\
            name: good
            matches:
              layout: test
            rules:
              - name: r
                when: "true"
                approvers:
                  any_of: [alice]
        """))
        (policies_dir / "bad.yaml").write_text("{ broken [[[")

        engine = PolicyEngine(d)
        with pytest.raises(PolicyLoadError):
            engine.load_policies(policies_dir)

    def test_two_policies_match_first_by_filename_sort(self, tmp_path: Path) -> None:
        """Policies loaded in sorted filename order — first match wins."""
        d = _make_directory(tmp_path)
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()

        (policies_dir / "01_first.yaml").write_text(textwrap.dedent("""\
            name: first_policy
            matches:
              layout: financial_decision
            rules:
              - name: r
                when: "true"
                approvers:
                  any_of: [alice]
        """))
        (policies_dir / "02_second.yaml").write_text(textwrap.dedent("""\
            name: second_policy
            matches:
              layout: financial_decision
            rules:
              - name: r
                when: "true"
                approvers:
                  any_of: [bob]
        """))

        engine = PolicyEngine(d)
        engine.load_policies(policies_dir)
        plan = engine.evaluate({"layout": "financial_decision", "subject": "Test"})
        assert plan.matched_policy_name == "first_policy"

    def test_policy_with_no_rules_skipped(self, tmp_path: Path) -> None:
        """Policy with empty rules list doesn't match, falls through."""
        d = _make_directory(tmp_path)
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()

        (policies_dir / "empty.yaml").write_text(textwrap.dedent("""\
            name: empty_rules
            matches:
              layout: financial_decision
            rules: []
        """))
        (policies_dir / "fallback.yaml").write_text(textwrap.dedent("""\
            name: fallback
            matches:
              layout: null
            rules:
              - name: catch_all
                when: "true"
                approvers:
                  any_of: [alice]
        """))

        engine = PolicyEngine(d)
        engine.load_policies(policies_dir)
        plan = engine.evaluate({"layout": "financial_decision", "subject": "Test"})
        assert plan.matched_policy_name == "fallback"

    def test_unknown_approver_fails_at_load_time(self, tmp_path: Path) -> None:
        d = _make_directory(tmp_path)
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()

        (policies_dir / "bad_ref.yaml").write_text(textwrap.dedent("""\
            name: bad_ref
            matches:
              layout: test
            rules:
              - name: r
                when: "true"
                approvers:
                  any_of: [nonexistent_person]
        """))

        engine = PolicyEngine(d)
        with pytest.raises(PolicyLoadError, match="unknown approver"):
            engine.load_policies(policies_dir)
