"""Verify database schema against PRD §6.3 specification.

Usage: python scripts/verify_schema.py
Requires: postgres running on localhost:5432
"""

import asyncio
import sys

import asyncpg

DB_URL = "postgresql://deliberate:deliberate@localhost:5432/deliberate"

# PRD §6.3 schema specification
EXPECTED_TABLES = {
    "applications": {
        "columns": {
            "id": {"type": "text", "nullable": False, "default_contains": None},
            "display_name": {"type": "text", "nullable": False, "default_contains": None},
            "api_key_hash": {"type": "text", "nullable": False, "default_contains": None},
            "created_at": {"type": "timestamp with time zone", "nullable": False, "default_contains": "now()"},
        },
    },
    "interrupts": {
        "columns": {
            "id": {"type": "uuid", "nullable": False, "default_contains": None},
            "application_id": {"type": "text", "nullable": False, "default_contains": "'default'"},
            "thread_id": {"type": "text", "nullable": False, "default_contains": None},
            "trace_id": {"type": "text", "nullable": True, "default_contains": None},
            "layout": {"type": "text", "nullable": False, "default_contains": None},
            "payload": {"type": "jsonb", "nullable": False, "default_contains": None},
            "policy_name": {"type": "text", "nullable": True, "default_contains": None},
            "received_at": {"type": "timestamp with time zone", "nullable": False, "default_contains": "now()"},
        },
    },
    "approvals": {
        "columns": {
            "id": {"type": "uuid", "nullable": False, "default_contains": None},
            "interrupt_id": {"type": "uuid", "nullable": False, "default_contains": None},
            "approver_id": {"type": "text", "nullable": True, "default_contains": None},
            "acting_for": {"type": "text", "nullable": True, "default_contains": None},
            "status": {"type": "text", "nullable": False, "default_contains": None},
            "timeout_at": {"type": "timestamp with time zone", "nullable": False, "default_contains": None},
            "escalated_to": {"type": "uuid", "nullable": True, "default_contains": None},
            "delegation_reason": {"type": "text", "nullable": True, "default_contains": None},
            "created_at": {"type": "timestamp with time zone", "nullable": False, "default_contains": "now()"},
        },
    },
    "decisions": {
        "columns": {
            "id": {"type": "uuid", "nullable": False, "default_contains": None},
            "approval_id": {"type": "uuid", "nullable": False, "default_contains": None},
            "approver_email": {"type": "text", "nullable": False, "default_contains": None},
            "decision_type": {"type": "text", "nullable": False, "default_contains": None},
            "decision_payload": {"type": "jsonb", "nullable": True, "default_contains": None},
            "rationale_category": {"type": "text", "nullable": True, "default_contains": None},
            "rationale_notes": {"type": "text", "nullable": True, "default_contains": None},
            "decided_via": {"type": "text", "nullable": False, "default_contains": None},
            "review_duration_ms": {"type": "integer", "nullable": True, "default_contains": None},
            "signature": {"type": "text", "nullable": False, "default_contains": None},
            "decided_at": {"type": "timestamp with time zone", "nullable": False, "default_contains": "now()"},
        },
    },
    "ledger_entries": {
        "columns": {
            "id": {"type": "uuid", "nullable": False, "default_contains": None},
            "application_id": {"type": "text", "nullable": False, "default_contains": "'default'"},
            "interrupt_id": {"type": "uuid", "nullable": False, "default_contains": None},
            "decision_id": {"type": "uuid", "nullable": True, "default_contains": None},
            "resume_status": {"type": "text", "nullable": False, "default_contains": None},
            "resume_latency_ms": {"type": "integer", "nullable": True, "default_contains": None},
            "content": {"type": "jsonb", "nullable": False, "default_contains": None},
            "content_hash": {"type": "text", "nullable": False, "default_contains": None},
            "created_at": {"type": "timestamp with time zone", "nullable": False, "default_contains": "now()"},
        },
    },
    "approvers": {
        "columns": {
            "id": {"type": "text", "nullable": False, "default_contains": None},
            "email": {"type": "text", "nullable": False, "default_contains": None},
            "display_name": {"type": "text", "nullable": True, "default_contains": None},
            "ooo_active": {"type": "boolean", "nullable": True, "default_contains": "false"},
            "ooo_from": {"type": "timestamp with time zone", "nullable": True, "default_contains": None},
            "ooo_until": {"type": "timestamp with time zone", "nullable": True, "default_contains": None},
            "ooo_delegate_to": {"type": "text", "nullable": True, "default_contains": None},
        },
    },
}

EXPECTED_INDEXES = [
    "idx_interrupts_thread",
    "idx_approvals_pending",
    "idx_ledger_thread",
    "idx_ledger_created",
]


async def main() -> int:
    conn = await asyncpg.connect(DB_URL)
    errors: list[str] = []

    # Check each table
    for table_name, spec in EXPECTED_TABLES.items():
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = $1
            ORDER BY ordinal_position
            """,
            table_name,
        )

        if not rows:
            errors.append(f"TABLE MISSING: {table_name} (PRD §6.3)")
            continue

        actual_cols = {r["column_name"]: r for r in rows}

        for col_name, col_spec in spec["columns"].items():
            if col_name not in actual_cols:
                errors.append(f"{table_name}.{col_name}: COLUMN MISSING (PRD §6.3)")
                continue

            actual = actual_cols[col_name]

            # Check type
            if col_spec["type"] not in actual["data_type"]:
                errors.append(
                    f"{table_name}.{col_name}: type mismatch — "
                    f"expected '{col_spec['type']}', got '{actual['data_type']}' (PRD §6.3)"
                )

            # Check nullable
            actual_nullable = actual["is_nullable"] == "YES"
            if col_spec["nullable"] != actual_nullable:
                errors.append(
                    f"{table_name}.{col_name}: nullable mismatch — "
                    f"expected {'NULL' if col_spec['nullable'] else 'NOT NULL'}, "
                    f"got {'NULL' if actual_nullable else 'NOT NULL'} (PRD §6.3)"
                )

            # Check default
            if col_spec["default_contains"]:
                actual_default = actual["column_default"] or ""
                if col_spec["default_contains"].lower() not in actual_default.lower():
                    errors.append(
                        f"{table_name}.{col_name}: default mismatch — "
                        f"expected to contain '{col_spec['default_contains']}', "
                        f"got '{actual_default}' (PRD §6.3)"
                    )

        # Check for extra columns not in spec
        for col_name in actual_cols:
            if col_name not in spec["columns"]:
                errors.append(
                    f"{table_name}.{col_name}: EXTRA COLUMN not in PRD §6.3 spec"
                )

    # Check indexes
    idx_rows = await conn.fetch(
        """
        SELECT indexname FROM pg_indexes WHERE schemaname = 'public'
        """
    )
    actual_indexes = {r["indexname"] for r in idx_rows}

    for idx_name in EXPECTED_INDEXES:
        if idx_name not in actual_indexes:
            errors.append(f"INDEX MISSING: {idx_name} (PRD §6.3)")

    # Check seed row
    seed = await conn.fetchrow("SELECT * FROM applications WHERE id = 'default'")
    if seed is None:
        errors.append("SEED ROW MISSING: applications WHERE id='default' (PRD §6.5)")

    await conn.close()

    if errors:
        print(f"\n{'='*60}")
        print(f"SCHEMA VERIFICATION FAILED — {len(errors)} issue(s):")
        print(f"{'='*60}\n")
        for e in errors:
            print(f"  ✗ {e}")
        print()
        return 1
    else:
        print("\n✓ Schema verification passed — all tables, columns, indexes match PRD §6.3\n")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
