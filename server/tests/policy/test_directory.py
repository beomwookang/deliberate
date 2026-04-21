"""Tests for the approver directory (Phase 1.1)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from deliberate_server.policy.directory import (
    ApproverDirectory,
    ApproverDirectoryError,
    ApproverNotFoundError,
)


@pytest.fixture()
def valid_yaml(tmp_path: Path) -> Path:
    """Write a valid approvers.yaml and return its path."""
    content = textwrap.dedent("""\
        approvers:
          - id: finance_lead
            email: priya@acme.com
            display_name: "Priya Sharma"
            out_of_office:
              active: false
              from: null
              until: null
              delegate_to: null
          - id: cfo
            email: cfo@acme.com
            display_name: "Alex Chen"
          - id: junior
            email: junior@acme.com

        groups:
          - id: finance_team
            members: [finance_lead, cfo]
          - id: all_finance
            members: [finance_lead, cfo, junior]
    """)
    p = tmp_path / "approvers.yaml"
    p.write_text(content)
    return p


class TestLoadValid:
    def test_load_counts(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        assert d.approver_count == 3
        assert d.group_count == 2

    def test_load_approver_details(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        entry = d.get_approver("finance_lead")
        assert entry is not None
        assert entry.email == "priya@acme.com"
        assert entry.display_name == "Priya Sharma"

    def test_load_missing_optional_fields(self, valid_yaml: Path) -> None:
        """Approver without display_name or out_of_office should load fine."""
        d = ApproverDirectory()
        d.load(valid_yaml)
        entry = d.get_approver("junior")
        assert entry is not None
        assert entry.email == "junior@acme.com"
        assert entry.display_name is None
        assert entry.out_of_office.active is False


class TestLoadInvalid:
    def test_file_not_found(self, tmp_path: Path) -> None:
        d = ApproverDirectory()
        with pytest.raises(ApproverDirectoryError, match="not found"):
            d.load(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("{ invalid yaml [[[")
        d = ApproverDirectory()
        with pytest.raises(ApproverDirectoryError, match="Invalid YAML"):
            d.load(p)

    def test_not_a_mapping(self, tmp_path: Path) -> None:
        p = tmp_path / "list.yaml"
        p.write_text("- item1\n- item2\n")
        d = ApproverDirectory()
        with pytest.raises(ApproverDirectoryError, match="must be a YAML mapping"):
            d.load(p)

    def test_duplicate_approver_id(self, tmp_path: Path) -> None:
        content = textwrap.dedent("""\
            approvers:
              - id: dup
                email: a@test.com
              - id: dup
                email: b@test.com
        """)
        p = tmp_path / "dup.yaml"
        p.write_text(content)
        d = ApproverDirectory()
        with pytest.raises(ApproverDirectoryError, match="Duplicate approver"):
            d.load(p)

    def test_group_references_unknown_member(self, tmp_path: Path) -> None:
        content = textwrap.dedent("""\
            approvers:
              - id: alice
                email: alice@test.com
            groups:
              - id: team
                members: [alice, bob]
        """)
        p = tmp_path / "bad_group.yaml"
        p.write_text(content)
        d = ApproverDirectory()
        with pytest.raises(ApproverDirectoryError, match="unknown approver 'bob'"):
            d.load(p)

    def test_duplicate_group_id(self, tmp_path: Path) -> None:
        content = textwrap.dedent("""\
            approvers:
              - id: alice
                email: alice@test.com
            groups:
              - id: team
                members: [alice]
              - id: team
                members: [alice]
        """)
        p = tmp_path / "dup_group.yaml"
        p.write_text(content)
        d = ApproverDirectory()
        with pytest.raises(ApproverDirectoryError, match="Duplicate group"):
            d.load(p)


class TestResolve:
    def test_resolve_individual(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        result = d.resolve("finance_lead")
        assert len(result) == 1
        assert result[0].id == "finance_lead"
        assert result[0].email == "priya@acme.com"
        assert result[0].display_name == "Priya Sharma"

    def test_resolve_group(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        result = d.resolve("finance_team")
        assert len(result) == 2
        emails = {a.email for a in result}
        assert emails == {"priya@acme.com", "cfo@acme.com"}

    def test_resolve_larger_group(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        result = d.resolve("all_finance")
        assert len(result) == 3

    def test_resolve_unknown_raises(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        with pytest.raises(ApproverNotFoundError, match="nonexistent"):
            d.resolve("nonexistent")


class TestHotReload:
    def test_reload_detects_change(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        assert d.approver_count == 3

        # Rewrite file with an extra approver
        new_content = textwrap.dedent("""\
            approvers:
              - id: finance_lead
                email: priya@acme.com
                display_name: "Priya Sharma"
              - id: cfo
                email: cfo@acme.com
              - id: junior
                email: junior@acme.com
              - id: new_person
                email: new@acme.com
            groups:
              - id: finance_team
                members: [finance_lead, cfo]
        """)
        valid_yaml.write_text(new_content)
        reloaded = d.reload()
        assert reloaded is True
        assert d.approver_count == 4

    def test_reload_no_change(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        reloaded = d.reload()
        assert reloaded is False

    def test_reload_invalid_keeps_current(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        assert d.approver_count == 3

        # Write invalid YAML
        valid_yaml.write_text("{ broken yaml [[[")
        reloaded = d.reload()
        assert reloaded is False
        # Current state preserved
        assert d.approver_count == 3

    def test_reload_file_deleted_keeps_current(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        valid_yaml.unlink()
        reloaded = d.reload()
        assert reloaded is False
        assert d.approver_count == 3


class TestToDict:
    def test_to_dict_structure(self, valid_yaml: Path) -> None:
        d = ApproverDirectory()
        d.load(valid_yaml)
        info = d.to_dict()
        assert info["approver_count"] == 3
        assert info["group_count"] == 2
        assert "finance_lead" in info["approver_ids"]
        assert "finance_team" in info["group_ids"]
        assert info["file_hash"] is not None
