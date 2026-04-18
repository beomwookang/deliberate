"""Validate that all SQLAlchemy models are importable."""

from deliberate_server.db.models import (
    Application,
    Approval,
    Approver,
    Base,
    Decision,
    Interrupt,
    LedgerEntry,
)


def test_all_models_importable() -> None:
    assert Application.__tablename__ == "applications"
    assert Interrupt.__tablename__ == "interrupts"
    assert Approval.__tablename__ == "approvals"
    assert Decision.__tablename__ == "decisions"
    assert LedgerEntry.__tablename__ == "ledger_entries"
    assert Approver.__tablename__ == "approvers"


def test_base_metadata_has_all_tables() -> None:
    table_names = set(Base.metadata.tables.keys())
    expected = {
        "applications",
        "interrupts",
        "approvals",
        "decisions",
        "ledger_entries",
        "approvers",
    }
    assert expected == table_names
