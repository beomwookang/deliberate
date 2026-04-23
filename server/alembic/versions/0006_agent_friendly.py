"""Add api_keys, policies, policy_versions, approver_groups tables; extend approvers (M4+).

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- api_keys table ---
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.id"),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("scopes", ARRAY(sa.Text()), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_app", "api_keys", ["application_id"])

    # Backfill legacy key from applications table
    op.execute(
        """
        INSERT INTO api_keys (id, application_id, name, key_prefix, key_hash, scopes, created_by)
        SELECT
            gen_random_uuid(),
            id,
            'legacy',
            LEFT(api_key_hash, 16),
            api_key_hash,
            ARRAY['interrupts:write', 'approvals:read'],
            'migration-0006'
        FROM applications
        WHERE api_key_hash IS NOT NULL AND api_key_hash <> ''
        """
    )

    # --- policies table ---
    op.create_table(
        "policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.id"),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("application_id", "name", name="uq_policies_app_name"),
    )

    # --- policy_versions table ---
    op.create_table(
        "policy_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "policy_id",
            UUID(as_uuid=True),
            sa.ForeignKey("policies.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_policy_versions_policy", "policy_versions", ["policy_id", "version"])

    # --- approver_groups table ---
    op.create_table(
        "approver_groups",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.id"),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("members", ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_approver_groups_app", "approver_groups", ["application_id"])

    # --- extend approvers table ---
    op.add_column(
        "approvers",
        sa.Column(
            "application_id",
            sa.Text(),
            sa.ForeignKey("applications.id"),
            nullable=True,  # nullable during migration, backfilled below
        ),
    )
    op.add_column(
        "approvers",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=True,  # nullable during migration, backfilled below
        ),
    )
    op.add_column(
        "approvers",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,  # nullable during migration, backfilled below
        ),
    )

    # Backfill existing approver rows
    op.execute(
        "UPDATE approvers SET application_id = 'default', is_active = TRUE, updated_at = NOW()"
    )

    # Now tighten nullability
    op.alter_column("approvers", "application_id", nullable=False)
    op.alter_column("approvers", "is_active", nullable=False)
    op.alter_column("approvers", "updated_at", nullable=False)


def downgrade() -> None:
    # Reverse approvers columns
    op.drop_column("approvers", "updated_at")
    op.drop_column("approvers", "is_active")
    op.drop_column("approvers", "application_id")

    # Drop new tables in reverse dependency order
    op.drop_index("ix_approver_groups_app", table_name="approver_groups")
    op.drop_table("approver_groups")

    op.drop_index("ix_policy_versions_policy", table_name="policy_versions")
    op.drop_table("policy_versions")

    op.drop_table("policies")

    op.drop_index("ix_api_keys_app", table_name="api_keys")
    op.drop_index("ix_api_keys_hash", table_name="api_keys")
    op.drop_table("api_keys")
