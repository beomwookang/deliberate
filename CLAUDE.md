# CLAUDE.md — Session notes for Claude Code

This file is maintained across Claude Code sessions so future sessions have continuity. Do not delete entries; add new ones under dated headings.

## Project conventions

- Python package manager: uv
- Node package manager: pnpm
- Python style: ruff format, ruff check, mypy --strict
- Testing: pytest (Python), playwright (UI e2e)
- Commit style: conventional commits (feat:, fix:, chore:, docs:)
- Branch naming: {type}/{short-description} e.g. feat/policy-engine
- Never run destructive DB operations without asking
- Never commit secrets; use .env.example

## Architecture invariants (do not violate)

- Ledger is source of truth (PRD §6.5). Operational tables project from it.
- All business tables carry application_id, indexed leading with it.
- Schema-reserved fields (application_id, acting_for, ooo_*, backup_delegate) must be present even when inert.
- Policy expression language is fixed — do not extend without PRD update.
- Server knows nothing about LangGraph internals — that lives in SDK only.

## Key commands

```bash
# SDK
cd sdk && uv pip install -e ".[dev]" && uv run pytest

# Server
cd server && uv pip install -e ".[dev]" && uv run pytest

# UI
cd ui && pnpm install && pnpm dev

# Full stack
docker compose up -d

# Linting
cd sdk && ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/
cd server && ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/
cd ui && pnpm lint && pnpm typecheck
```

## Session log

### Session 1 — 2026-04-19 — Project bootstrap

- Created full repo structure matching PRD §6.1 architecture
- SDK: types.py with full Pydantic models for InterruptPayload, Decision, LedgerEntry per PRD §5.1/§5.3. decorator.py with @approval_gate stub. client.py with DeliberateClient stub. All raise NotImplementedError.
- Server: FastAPI app with /health endpoint. APScheduler worker with empty loop and SIGTERM handling. SQLAlchemy models for all 6 tables per PRD §6.3. Alembic migration 0001_initial with full schema and default application seed.
- UI: Next.js 14 App Router with Tailwind. Landing page, approval page placeholder at /a/[token]. Three layout component stubs (financial_decision, document_review, procedure_signoff).
- Examples: refund_agent skeleton using @approval_gate decorator.
- Docker Compose: 4 services (postgres:16, server, worker, ui) per PRD §6.7.
- CI: GitHub Actions with 3 jobs (sdk-check, server-check, ui-check) triggered on PR.
- Config: pydantic-settings for env-driven config. .env.example with all variables.
- All reserved/inert fields present: application_id (default 'default'), acting_for (null), ooo_* fields, delegation_reason, backup_delegate in policy schema.
- Next.js version: specified 14 per user constraint. Latest is 15+ but user explicitly said 14.
