"""Validate that the migration module is importable and well-formed."""

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_revisions_exist() -> None:
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    revisions = list(scripts.walk_revisions())
    assert len(revisions) == 2
    rev_ids = {r.revision for r in revisions}
    assert "0001" in rev_ids
    assert "0002" in rev_ids
