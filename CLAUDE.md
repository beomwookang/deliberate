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

### Session 2 — 2026-04-19 — Milestone M1 complete

#### What's implemented
- **SDK (Phase 1):** `@approval_gate` decorator with transparent `config` injection for thread_id. `DeliberateClient` with async httpx: submit_interrupt, poll_status, wait_for_decision (2s interval, configurable timeout), submit_resume_ack. Custom exceptions: `DeliberateTimeoutError`, `DeliberateServerError`. 23 unit tests.
- **Server (Phase 2+3):** All 8 endpoints implemented:
  - `POST /interrupts` — API key auth (SHA-256 hash comparison), payload validation against SDK's `InterruptPayload`, transactional interrupt+approval creation
  - `GET /approvals/{id}/status` — polling endpoint, returns decision details when decided
  - `GET /approvals/{id}/payload` — fetch interrupt data for UI rendering
  - `POST /approvals/{id}/decide` — decision with HMAC signature, ledger entry with SHA-256 content hash
  - `POST /approvals/{id}/resume-ack` — updates ledger with resume status/latency
  - `GET /ledger` — query by thread_id with JSONB path filter
  - Auth utilities: JWT tokens (HS256, jti/aud/iat/exp claims), API key hashing, content hash, HMAC signing
  - 25 server tests against real Postgres (NullPool for test isolation)
- **UI (Phase 4):** Approval page at `/a/[approval_id]` as async Server Component. Server-side fetch via `INTERNAL_API_URL`. `FinancialDecisionLayout` with amount card, customer info, agent reasoning, evidence table. `DecisionForm` client component with 4 decision buttons, rationale chips, notes, review_duration_ms measurement.
- **Example agent (Phase 5):** Three-node LangGraph graph (classify → approve_refund → process_refund). Runnable with `python agent.py`.
- **Integration test (Phase 6):** Full M1 flow test: interrupt → status(pending) → payload → decide → status(decided) → resume-ack → ledger query → content hash verification → 409 on double-decide.

#### Key decisions made during M1
- **SDK blocking poll, not LangGraph interrupt():** For M1, the `@approval_gate` decorator blocks the graph thread synchronously (submit → poll → return). It does NOT use LangGraph's `interrupt()` / `Command(resume=...)`. This is acceptable for M1; true graph pause/resume semantics can come in M2+.
- **Server depends on SDK for shared types:** `deliberate.types.InterruptPayload` is imported by the server. No type duplication. May refactor to `deliberate-core` package if circular issues arise.
- **Approval URLs use raw approval_id (UUID):** No signed JWT tokens in URLs for M1. UUID entropy (128 bits) is adequate. M2 will replace with signed tokens per PRD §6.6.
- **SECRET_KEY required, no default:** Server fails to start if SECRET_KEY is empty. No dev default.
- **NullPool for tests:** Server tests use `sqlalchemy.pool.NullPool` to avoid asyncpg connection pool state leaking between test functions.
- **Server Dockerfile uses repo root as build context:** Because the server imports the SDK package, the Dockerfile COPYs both `sdk/` and `server/` from the repo root.
- **LangGraph 0.4.10 verified:** Thread ID accessed via `config["configurable"]["thread_id"]`. Public API only (`langgraph.types.interrupt`, `langgraph.types.Command`).

#### M1 decisions deferred to M2
- Approval URLs use raw approval_id. M2 will replace with signed JWT tokens per PRD §6.6.
- No notifications (Slack, Email, Webhook) — approver URL copied from logs.
- No policy engine — single approver from `DEFAULT_APPROVER_EMAIL` env var.
- No timeout worker — approvals sit forever if ignored.
- Approver identity: `anonymous@deliberate.dev` hardcoded in DecisionForm. M2 adds magic link / OAuth.
- SDK blocking poll may move to true `interrupt()` / `Command(resume=...)` pattern.
- Server mypy --strict not fully passing due to mixed imports; address in M2.
- `deliberate-core` package extraction if SDK↔server coupling causes issues.

#### Known TODOs in code
- `sdk/src/deliberate/client.py:75` — `TODO(M2): Replace with signed token per PRD §6.6`
- `server/src/deliberate_server/api/routes/approvals.py:100` — `TODO(M2): Replace with signed token per PRD §6.6`
- `ui/app/a/[approval_id]/page.tsx:15` — `TODO(M2): Replace with signed token per PRD §6.6`
