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

### Session 3 — 2026-04-22 — Milestone M2a (Policy engine + Notifications)

#### What's implemented
- **PRD Draft v4:** Added `notify` field to policy rules, `notification_attempts` table, expression evaluator semantics for union types/missing fields, `webhooks.yaml` config, M2 split into M2a/M2b/M2c sub-milestones.
- **Phase 1.1 — Approver directory:** `ApproverDirectory` class loads `approvers.yaml`, resolves individual IDs and groups, hot-reloads via polling. Shared Pydantic models (`ApproverEntry`, `ApproverGroup`, `ResolvedApprover`) in SDK `types.py`. 18 tests.
- **Phase 1.2 — Policy engine:** Recursive descent parser (tokenizer → AST → evaluator) for the PRD §5.2 expression language. All operators: `<`, `>`, `<=`, `>=`, `==`, `!=`, `and`, `or`, `not`, `contains`. Missing field access → `false` (not error). `contains` on structured `agent_reasoning` falls back to `summary` field. `PolicyEngine` loads YAML policies, evaluates top-to-bottom first-match-wins, returns `ResolvedPlan`. 70 tests (50 expression + 20 engine).
- **Phase 1.3 — M1 migration path:** `DEFAULT_APPROVER_EMAIL` env var still works as fallback when no policy matches (deprecation warning logged). Returns 400 if no policy matches and no env var set.
- **Phase 1.4 — Policy-driven interrupt handler:** `POST /interrupts` calls `policy_engine.evaluate(payload)`. Auto-approve writes ledger directly (`approver_email=system`, `rationale_category=auto_approved_by_policy`, `review_duration_ms=0`). `any_of` creates single approval row; `all_of` creates one per approver.
- **Phase 2.1 — Notifier protocol + dispatcher:** `Notifier` protocol, `NotificationDispatcher` with `asyncio.gather` parallel dispatch. `notification_attempts` table (migration 0003). Individual channel failures non-fatal. 7 dispatcher tests.
- **Phase 2.2 — Email adapter:** `aiosmtplib` async SMTP, HTML + plain-text templates with "Review and decide" button. Retries 3x with backoff on connection failure, immediate fail on auth error.
- **Phase 2.3 — Webhook adapter:** HMAC-SHA256 signed payloads (`X-Deliberate-Signature`). Multi-destination fan-out to all active webhooks in `webhooks.yaml`. Retries 3x on 5xx, no retry on 4xx. 9 tests.
- **Phase 2.4 — Slack adapter:** `slack_sdk` with `users.lookupByEmail` → `conversations.open` → `chat.postMessage`. Block Kit message with header, reasoning, amount, and "Review and decide" button. User cache (1h TTL). 7 tests.
- **Phase 2.5 — Wiring:** Dispatcher called from interrupt handler after approval creation. MailHog added to docker-compose with `profiles: ["dev"]`.

#### Key decisions made during M2a
- **Simple polling for hot-reload, not watchdog:** Used a background thread with 5s polling instead of the `watchdog` package. Avoids an extra dependency; the polling interval is configurable and adequate for config file changes.
- **No eval() anywhere:** The expression parser is a purpose-built recursive descent parser. Security-critical: we're evaluating user-provided YAML against agent payloads.
- **Missing field access → false, not error:** Per user direction (Correction 3). Makes policies author-friendly across payload variants (string vs structured `agent_reasoning`).
- **`contains` on structured reasoning → summary fallback:** Per user direction. `agent_reasoning contains 'fraud'` checks `summary` field when reasoning is structured.
- **Auto-approve shape:** `approver_email="system"`, `rationale_category="auto_approved_by_policy"`, `review_duration_ms=0`. No approval row created.
- **env_prefix stays empty:** Kept `env_prefix=""` in pydantic-settings to maintain backward compatibility with existing docker-compose and env vars (`SECRET_KEY`, `DATABASE_URL`, etc.).
- **MailHog in dev profile:** `profiles: ["dev"]` per user direction (not `"test"`). Used for manual UX testing of email readability.
- **aiohttp added as dependency:** Required by `slack_sdk`'s async client.

#### M2a decisions deferred to M2b/M2c
- Timeout worker and escalation logic execution (M2b).
- `document_review` and `procedure_signoff` layouts (M2b).
- Slack inline approval (v1.2, per PRD §6.5).
- Signed approval URL tokens (PRD §6.6 — still using raw UUIDs).
- OAuth for approvers (magic-link style from M1 still active).
- Quickstart docs and v0.1.0 release (M2c).

#### Test counts
- Server: 160 tests (88 policy + 23 notification + 49 existing M1)
- SDK: 27 tests
- Total: 187 tests, all passing on main

### Session 3b — 2026-04-22 — M2a validation fixes + all_of multi-approver

#### What's implemented
- **Fix 1 — mypy --strict:** 11 errors → 0. Renamed shadowed variables, removed stale type: ignore comments, added type narrowing asserts, cast slack_sdk returns.
- **Fix 2 — ruff lint:** 53 errors → 0. Excluded `alembic/versions/` from ruff config. Fixed import ordering, SIM117 nested with, E501 line lengths in email template, unused variables in tests. All code formatted clean.
- **Fix 3 — all_of multi-approver end-to-end:**
  - New `approval_group_id` and `approval_mode` columns on approvals table (migration 0004)
  - `POST /interrupts` response now includes `approval_group_id`, `approval_ids[]`, `approval_mode` (backward compat: `approval_id` still present)
  - New `GET /approval-groups/{group_id}/status` endpoint with aggregation
  - Decision aggregation for all_of: all approve → merge notes, any reject → short-circuit reject, approve+modify → most restrictive (smallest numeric value)
  - any_of: first decision wins, other approvals marked "superseded"
  - Ledger entries get `approval_group: {group_id, role}` field
  - SDK: `submit_interrupt()` returns `InterruptResult`, `poll_group_status()` for groups, `wait_for_decision(use_group=True)` for all_of
  - Decorator handles auto_approve return and group-based polling
  - 6 new integration tests for approval groups

#### Key decisions
- **"Most restrictive" = smallest numeric value:** For M2a, when all_of has mixed approve+modify decisions, the modification with the smallest numeric value in `decision_payload` wins. M3 can make this configurable per policy.
- **Early reject in all_of:** If any approver rejects, the group is immediately decided as reject. Other approvers' pending approvals are not superseded (they can still record their decision for audit, but the group outcome is already set).
- **conftest uses drop_all + create_all:** Changed from `create_all` only to `drop_all` + `create_all` to pick up new columns in tests without running Alembic.
- **alembic/versions/ excluded from ruff:** Auto-generated migration boilerplate uses `Union[str, None]` and unsorted imports that are not worth fixing. Documented in pyproject.toml.

#### Test counts
- Server: 212 tests (was 206)
- SDK: 30 tests (was 27)
- Total: 242 tests, all passing. mypy --strict clean. ruff clean.

### Session 5 — 2026-04-23 — Milestone M3 + M4 complete

#### M3 — What's implemented
- **M3a — Security and Identity:**
  - Signed JWT approval tokens wired into URL flow (`/a/{jwt}` with backward compat for raw UUIDs)
  - New `/auth/verify-approval-token` endpoint + auth router registered in main.py
  - FOR UPDATE lock on decide endpoint (prevents concurrent double-decide race)
  - Escalation depth guard (max_escalation_depth=3, follows FK chain, falls back to fail)
  - HKDF key derivation: 3 separate keys (jwt_key, hmac_key, content_key) from SECRET_KEY via `cryptography` HKDF
  - Magic link approver identity: POST /auth/magic-link, POST /auth/verify-magic-link, POST /auth/verify-session. DecisionForm shows "Verify Your Identity" gate before decision form.

- **M3b — Ledger and Audit:**
  - `resume_events` table (migration 0005): resume-ack no longer mutates ledger content JSONB
  - `prev_hash` column on ledger_entries: hash chain across all 4 creation paths (decision, auto-approve, timeout, escalation)
  - Enhanced GET /ledger: approver_id, date_from, date_to, q (ILIKE) filters + cursor-based pagination
  - GET /ledger/export/json and GET /ledger/export/csv with same filters
  - Unified audit view: decided approvals show full layout + DecisionOverlay instead of generic message
  - GET /approvals/{id}/payload now returns decision data for decided approvals

- **M3c — Developer Experience:**
  - DecisionForm uses NEXT_PUBLIC_API_URL or same-origin /api proxy (next.config.js rewrites)
  - Shared AgentReasoningSection extracted; all 3 layouts deduplicated
  - CONTRIBUTING.md with dev setup, code style, PR process, architecture overview

#### M4 — What's implemented
- **Three new layouts:** data_access (resource/scope/risk), content_moderation (flagged items/policy refs), code_deployment (diff/tests/rollback)
- **Custom layout SDK docs:** docs/custom-layouts.md with step-by-step guide and example
- **Observability:** prometheus_client with 5 metrics (interrupts, decisions, duration, timeouts, escalations), GET /metrics endpoint, structured logging
- **Graceful shutdown:** _shutting_down flag, health endpoint returns degraded status
- **OTLP export:** opentelemetry-sdk integration, emit_ledger_span() on decision and auto-approve paths, disabled by default (env-gated)
- **Security docs:** docs/security.md with STRIDE threat model, HKDF key management, production recommendations
- **README updated:** reflects all M1-M4 features, links to docs

#### Key decisions made during M3/M4
- **HKDF salt=None:** Master key is high-entropy (required SECRET_KEY), so no salt needed per HKDF spec.
- **Magic link returns token in response (dev mode):** For development/testing convenience. Production should email the link.
- **Cursor pagination uses base64(JSON{ts,id}):** Stable pagination across concurrent inserts.
- **resume_events separate from ledger:** Preserves append-only immutability invariant. Operational columns (resume_status, resume_latency_ms) still updated for quick queries.
- **OTLP lazy-init:** Tracer initialized on first emit_ledger_span call, not at import. No-op if OTEL_EXPORTER_OTLP_ENDPOINT not set.
- **Prometheus metrics are lightweight counters/histograms:** No per-request tracing overhead.
- **conftest uses DROP SCHEMA CASCADE + CREATE SCHEMA:** Handles FK dependencies cleanly when adding new tables.

#### Test counts
- Server: 219 tests
- SDK: 30 tests
- Total: 249 tests, all passing. mypy --strict clean. ruff clean. TypeScript clean. ESLint clean.
