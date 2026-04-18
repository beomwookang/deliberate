"""Validate that the migration module is importable and well-formed."""

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_revision_exists() -> None:
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    revisions = list(scripts.walk_revisions())
    assert len(revisions) == 1
    assert revisions[0].revision == "0001"
    assert revisions[0].down_revision is None
