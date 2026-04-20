"""Fix approvers.ooo_active: add server default and ensure NOT NULL.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Set default for existing NULL rows (if any)
    op.execute("UPDATE approvers SET ooo_active = FALSE WHERE ooo_active IS NULL")
    # Add server default
    op.alter_column(
        "approvers",
        "ooo_active",
        server_default=sa.text("FALSE"),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "approvers",
        "ooo_active",
        server_default=None,
        nullable=True,
    )
