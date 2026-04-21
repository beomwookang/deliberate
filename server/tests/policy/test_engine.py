"""Tests for the PolicyEngine (Phase 1.2)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from deliberate_server.policy.directory import ApproverDirectory
from deliberate_server.policy.engine import (
    NoMatchingPolicyError,
    PolicyEngine,
    PolicyLoadError,
)


@pytest.fixture()
def approvers_yaml(tmp_path: Path) -> Path:
    content = textwrap.dedent("""\
        approvers:
          - id: finance_lead
            email: priya@acme.com
            display_name: "Priya Sharma"
          - id: cfo
            email: cfo@acme.com
            display_name: "Alex Chen"
          - id: junior
            email: junior@acme.com
        groups:
          - id: finance_team
            members: [finance_lead, cfo]
    """)
    p = tmp_path / "approvers.yaml"
    p.write_text(content)
    return p


@pytest.fixture()
def directory(approvers_yaml: Path) -> ApproverDirectory:
    d = ApproverDirectory()
    d.load(approvers_yaml)
    return d


@pytest.fixture()
def policies_dir(tmp_path: Path) -> Path:
    d = tmp_path / "policies"
    d.mkdir()
    return d


def _write_policy(policies_dir: Path, name: str, content: str) -> Path:
    p = policies_dir / f"{name}.yaml"
    p.write_text(textwrap.dedent(content))
    return p


class TestPolicyLoading:
    def test_load_valid_policy(self, directory: ApproverDirectory, policies_dir: Path) -> None:
        _write_policy(
            policies_dir,
            "refund",
            """\
            name: refund_approval
            matches:
              layout: financial_decision
              subject_contains: "Refund"
            rules:
              - name: auto_small
                when: "amount.value < 100"
                action: auto_approve
                rationale: "Below threshold"
              - name: standard
                when: "amount.value >= 100"
                approvers:
                  any_of: [finance_team]
                timeout: 4h
                on_timeout: escalate
                escalate_to: finance_lead
                notify: [email, slack]
        """,
        )
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)
        assert engine.policy_count == 1
        assert "refund_approval" in engine.policy_names

    def test_load_empty_dir_warns(self, directory: ApproverDirectory, policies_dir: Path) -> None:
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)
        assert engine.policy_count == 0

    def test_load_nonexistent_dir(self, directory: ApproverDirectory) -> None:
        engine = PolicyEngine(directory)
        with pytest.raises(PolicyLoadError, match="not found"):
            engine.load_policies("/nonexistent/path")

    def test_invalid_expression_fails_on_load(
        self, directory: ApproverDirectory, policies_dir: Path
    ) -> None:
        _write_policy(
            policies_dir,
            "bad",
            """\
            name: bad_policy
            matches:
              layout: financial_decision
            rules:
              - name: bad_rule
                when: "amount.value @@ 100"
                approvers:
                  any_of: [finance_team]
        """,
        )
        engine = PolicyEngine(directory)
        with pytest.raises(PolicyLoadError, match="Invalid expression"):
            engine.load_policies(policies_dir)

    def test_unknown_approver_fails_on_load(
        self, directory: ApproverDirectory, policies_dir: Path
    ) -> None:
        _write_policy(
            policies_dir,
            "bad_approver",
            """\
            name: bad_approver_policy
            matches:
              layout: financial_decision
            rules:
              - name: route
                when: "true"
                approvers:
                  any_of: [nonexistent_team]
        """,
        )
        engine = PolicyEngine(directory)
        with pytest.raises(PolicyLoadError, match="unknown approver"):
            engine.load_policies(policies_dir)


class TestRuleMatching:
    @pytest.fixture()
    def engine(self, directory: ApproverDirectory, policies_dir: Path) -> PolicyEngine:
        _write_policy(
            policies_dir,
            "refund",
            """\
            name: refund_approval
            matches:
              layout: financial_decision
              subject_contains: "Refund"
            rules:
              - name: auto_small
                when: "amount.value < 100"
                action: auto_approve
                rationale: "Below $100 threshold"
              - name: standard
                when: "amount.value >= 100 and amount.value < 5000"
                approvers:
                  any_of: [finance_team]
                timeout: 4h
                on_timeout: escalate
                escalate_to: finance_lead
                notify: [email, slack]
              - name: high_value
                when: "amount.value >= 5000"
                approvers:
                  all_of: [finance_lead, cfo]
                timeout: 8h
                on_timeout: fail
                require_rationale: true
                notify: [email, slack, webhook]
        """,
        )
        eng = PolicyEngine(directory)
        eng.load_policies(policies_dir)
        return eng

    def test_auto_approve_small(self, engine: PolicyEngine) -> None:
        payload = {
            "layout": "financial_decision",
            "subject": "Refund for order #123",
            "amount": {"value": 50.0, "currency": "USD"},
        }
        plan = engine.evaluate(payload)
        assert plan.action == "auto_approve"
        assert plan.matched_rule_name == "auto_small"
        assert plan.rationale == "Below $100 threshold"
        assert plan.approvers == []

    def test_standard_any_of(self, engine: PolicyEngine) -> None:
        payload = {
            "layout": "financial_decision",
            "subject": "Refund for order #456",
            "amount": {"value": 750.0, "currency": "USD"},
        }
        plan = engine.evaluate(payload)
        assert plan.action == "request_human"
        assert plan.matched_rule_name == "standard"
        assert plan.approval_mode == "any_of"
        assert len(plan.approvers) == 2  # finance_team has 2 members
        assert plan.timeout_seconds == 4 * 3600
        assert set(plan.notify_channels) == {"email", "slack"}
        assert plan.on_timeout == "escalate"
        assert plan.escalate_to == "finance_lead"

    def test_high_value_all_of(self, engine: PolicyEngine) -> None:
        payload = {
            "layout": "financial_decision",
            "subject": "Refund for order #789",
            "amount": {"value": 10000.0, "currency": "USD"},
        }
        plan = engine.evaluate(payload)
        assert plan.action == "request_human"
        assert plan.matched_rule_name == "high_value"
        assert plan.approval_mode == "all_of"
        assert len(plan.approvers) == 2
        emails = {a.email for a in plan.approvers}
        assert emails == {"priya@acme.com", "cfo@acme.com"}
        assert plan.timeout_seconds == 8 * 3600
        assert plan.require_rationale is True
        assert "webhook" in plan.notify_channels

    def test_first_match_wins(self, engine: PolicyEngine) -> None:
        """Amount exactly at boundary — first matching rule wins."""
        payload = {
            "layout": "financial_decision",
            "subject": "Refund for order #100",
            "amount": {"value": 100.0, "currency": "USD"},
        }
        plan = engine.evaluate(payload)
        assert plan.matched_rule_name == "standard"  # >= 100 and < 5000

    def test_policy_version_hash_present(self, engine: PolicyEngine) -> None:
        payload = {
            "layout": "financial_decision",
            "subject": "Refund test",
            "amount": {"value": 50.0},
        }
        plan = engine.evaluate(payload)
        assert plan.policy_version_hash
        assert len(plan.policy_version_hash) == 64  # SHA-256 hex


class TestMatcherFiltering:
    def test_layout_mismatch_skips_policy(
        self, directory: ApproverDirectory, policies_dir: Path
    ) -> None:
        _write_policy(
            policies_dir,
            "refund",
            """\
            name: refund_only
            matches:
              layout: financial_decision
            rules:
              - name: catch_all
                when: "true"
                approvers:
                  any_of: [finance_lead]
        """,
        )
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)

        payload = {"layout": "document_review", "subject": "Contract review"}
        with pytest.raises(NoMatchingPolicyError):
            engine.evaluate(payload)

    def test_subject_contains_mismatch(
        self, directory: ApproverDirectory, policies_dir: Path
    ) -> None:
        _write_policy(
            policies_dir,
            "refund",
            """\
            name: refund_only
            matches:
              layout: financial_decision
              subject_contains: "Refund"
            rules:
              - name: catch_all
                when: "true"
                approvers:
                  any_of: [finance_lead]
        """,
        )
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)

        payload = {"layout": "financial_decision", "subject": "Expense approval #42"}
        with pytest.raises(NoMatchingPolicyError):
            engine.evaluate(payload)

    def test_null_layout_matches_anything(
        self, directory: ApproverDirectory, policies_dir: Path
    ) -> None:
        _write_policy(
            policies_dir,
            "default",
            """\
            name: catch_all
            matches:
              layout: null
            rules:
              - name: route
                when: "true"
                approvers:
                  any_of: [finance_lead]
        """,
        )
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)

        payload = {"layout": "anything_goes", "subject": "Whatever"}
        plan = engine.evaluate(payload)
        assert plan.action == "request_human"


class TestMultiplePolicies:
    def test_first_matching_policy_wins(
        self, directory: ApproverDirectory, policies_dir: Path
    ) -> None:
        _write_policy(
            policies_dir,
            "01_specific",
            """\
            name: specific_refund
            matches:
              layout: financial_decision
              subject_contains: "Refund"
            rules:
              - name: route
                when: "true"
                approvers:
                  any_of: [finance_lead]
                notify: [slack]
        """,
        )
        _write_policy(
            policies_dir,
            "02_general",
            """\
            name: general_financial
            matches:
              layout: financial_decision
            rules:
              - name: route
                when: "true"
                approvers:
                  any_of: [cfo]
                notify: [email]
        """,
        )
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)

        payload = {"layout": "financial_decision", "subject": "Refund #123"}
        plan = engine.evaluate(payload)
        assert plan.matched_policy_name == "specific_refund"
        assert plan.notify_channels == ["slack"]

    def test_no_match_raises(self, directory: ApproverDirectory, policies_dir: Path) -> None:
        _write_policy(
            policies_dir,
            "refund",
            """\
            name: refund_only
            matches:
              layout: financial_decision
            rules:
              - name: never_match
                when: "false"
                approvers:
                  any_of: [finance_lead]
        """,
        )
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)

        payload = {"layout": "financial_decision", "subject": "Test"}
        with pytest.raises(NoMatchingPolicyError):
            engine.evaluate(payload)


class TestPolicyHotReload:
    def test_reload_detects_change(self, directory: ApproverDirectory, policies_dir: Path) -> None:
        _write_policy(
            policies_dir,
            "test",
            """\
            name: test_policy
            matches:
              layout: financial_decision
            rules:
              - name: route
                when: "true"
                approvers:
                  any_of: [finance_lead]
        """,
        )
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)
        assert engine.policy_count == 1

        # Add a second policy
        _write_policy(
            policies_dir,
            "test2",
            """\
            name: test_policy_2
            matches:
              layout: document_review
            rules:
              - name: route
                when: "true"
                approvers:
                  any_of: [cfo]
        """,
        )
        reloaded = engine.reload()
        assert reloaded is True
        assert engine.policy_count == 2

    def test_reload_no_change(self, directory: ApproverDirectory, policies_dir: Path) -> None:
        _write_policy(
            policies_dir,
            "test",
            """\
            name: test_policy
            matches:
              layout: financial_decision
            rules:
              - name: route
                when: "true"
                approvers:
                  any_of: [finance_lead]
        """,
        )
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)
        assert engine.reload() is False

    def test_reload_invalid_keeps_current(
        self, directory: ApproverDirectory, policies_dir: Path
    ) -> None:
        _write_policy(
            policies_dir,
            "test",
            """\
            name: test_policy
            matches:
              layout: financial_decision
            rules:
              - name: route
                when: "true"
                approvers:
                  any_of: [finance_lead]
        """,
        )
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)

        # Corrupt the file — get path from policies_dir
        policy_file = policies_dir / "test.yaml"
        policy_file.write_text("{ broken yaml [[[")
        reloaded = engine.reload()
        assert reloaded is False
        assert engine.policy_count == 1

    def test_version_hash_changes_on_reload(
        self, directory: ApproverDirectory, policies_dir: Path
    ) -> None:
        _write_policy(
            policies_dir,
            "test",
            """\
            name: test_policy
            matches:
              layout: financial_decision
            rules:
              - name: route
                when: "true"
                approvers:
                  any_of: [finance_lead]
        """,
        )
        engine = PolicyEngine(directory)
        engine.load_policies(policies_dir)

        payload = {"layout": "financial_decision", "subject": "Test"}
        plan1 = engine.evaluate(payload)
        hash1 = plan1.policy_version_hash

        # Modify policy
        _write_policy(
            policies_dir,
            "test",
            """\
            name: test_policy
            matches:
              layout: financial_decision
            rules:
              - name: route_v2
                when: "true"
                approvers:
                  any_of: [cfo]
        """,
        )
        engine.reload()
        plan2 = engine.evaluate(payload)
        assert plan2.policy_version_hash != hash1
