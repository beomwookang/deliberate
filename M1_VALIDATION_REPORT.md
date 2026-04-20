# M1 Validation Report

Run on: 2026-04-20
Rebuild clean: Attempted (Docker build failed — see A-1)
Time to produce: ~1 hour

## Summary

| Part | Status | Count of findings |
|---|---|---|
| A. Smoke & build | ❌ | 3 |
| B. Schema integrity | ⚠️ | 1 |
| C. End-to-end assertions | ⚠️ | 2 |
| D. Schema drift (type sharing) | ⚠️ | 1 |
| E. Reserved fields | ✅ | 0 |
| F. Adversarial / failure modes | ⚠️ | 1 |
| G. Dependencies | ✅ | 0 |

## Findings

### Critical (blocks manual testing)

- **A-1: Docker build fails — SDK readme path breaks in container.**
  - `sdk/pyproject.toml` has `readme = "../README.md"`. When the SDK is copied to `/sdk/` in the Docker container, this relative path resolves to `/README.md` which doesn't exist. Hatchling refuses to build.
  - **Repro:** `docker compose up --build` → fails at `RUN uv pip install --system /sdk` with `OSError: Readme file does not exist: ../README.md`
  - **Impact:** The server and worker containers cannot be built. `docker compose up` does not work at all.
  - **Fix:** Change `readme = "../README.md"` to `readme = {text = "...", content-type = "text/markdown"}` or remove it, or copy README.md alongside sdk/ in the Dockerfile.
  - **File:** `sdk/pyproject.toml:9`

### Important (fix before M2 starts)

- **A-2: Server tests flaky on virgin database.**
  - On first run after `docker compose down -v` (no tables exist), the conftest's `_ensure_tables()` creates tables in one engine/connection, then each test's `client` fixture creates a fresh NullPool engine. The first successful test leaves asyncpg in a state where subsequent tests hit `InterfaceError: cannot perform operation: another operation is in progress`. 
  - 12/29 tests fail on cold start, 0/29 fail on second run.
  - **File:** `server/tests/conftest.py`

- **A-3: No UI tests (Playwright).**
  - `pnpm test` → "No tests configured yet". The Phase 4 plan mentioned Playwright tests but none were written. The approval page, layout rendering, and decision form have zero test coverage.
  - **Impact:** UI bugs (broken layouts, JS errors, submit failures) won't be caught before manual testing.

- **B-1: `approvers.ooo_active` schema mismatch.**
  - PRD §6.3 specifies `ooo_active BOOLEAN DEFAULT FALSE` — implying nullable (no NOT NULL clause). The SQLAlchemy model defines it as `Mapped[bool]` (non-nullable) with `default=False` (Python-side only, no `server_default`).
  - Result: column is NOT NULL in the DB, and has no server-level DEFAULT.
  - **File:** `server/src/deliberate_server/db/models.py:158`

- **C5-1: No decision_type enum validation.**
  - `POST /approvals/{id}/decide` with `decision_type: "maybe"` returns 200. PRD §6.3 specifies valid values are `approve, modify, escalate, reject`. The server does not validate against this enum.
  - Invalid types get written to `decisions` and `ledger_entries.content` as-is.
  - **Impact:** Dirty data in the ledger if clients send invalid types.
  - **File:** `server/src/deliberate_server/api/routes/approvals.py` (DecideRequest model)

- **C6-1: 1MB payload cap NOT enforced.**
  - PRD §4.3: "Deliberate is a decision-routing system, not a document store. Links out to S3 or similar for heavy artifacts." A 2MB payload submits successfully (200 OK).
  - No size check exists anywhere in the codebase.
  - **Impact:** Users can store unbounded payloads, potentially causing performance issues.

- **D-1: Ledger content JSON not validated against SDK LedgerEntry schema.**
  - The server constructs `ledger_entries.content` as a raw dict in `approvals.py:176-207`. It never validates this dict against the SDK's `LedgerEntry` Pydantic model.
  - If someone changes the dict structure in the server without updating the SDK type (or vice versa), there's no compile-time or test-time detection of drift.
  - The SDK imports are correct for `InterruptPayload` (validated on ingest), but the canonical ledger schema has no runtime validation.
  - **File:** `server/src/deliberate_server/api/routes/approvals.py:176`

### Nice-to-have (M2 backlog)

- **F5-1: No server-side HTML sanitization.**
  - XSS payloads (`<script>alert('xss')</script>`) are stored verbatim and returned by the API. React's JSX escaping protects the Next.js UI, but non-React API consumers would need to sanitize themselves.
  - Acceptable for M1 (self-hosted, trusted agents), but worth documenting.

- **F6-1: Long word (5000 chars) handling in UI untested.**
  - Data round-trips correctly at the API level. Browser rendering of a 5000-char no-space string would likely overflow on mobile. Can't verify without a running UI.

- **G-1: `langgraph-sdk` pulled in as transitive dependency.**
  - The SDK depends on `langgraph>=0.3,<0.5` which transitively installs `langgraph-sdk` (the LangGraph Cloud client). User was explicit that "Do NOT use langgraph_sdk — that's a different package." It's not used in code, but it's installed, which could confuse developers.

## Positive observations

1. **Content hash round-trips perfectly.** All 5 independent hash verifications passed — the canonical JSON algorithm is deterministic and the hash matches after DB storage/retrieval.
2. **Concurrent agents stay isolated.** No cross-contamination detected even with interleaved requests.
3. **JWT utilities work correctly.** Tampered tokens rejected, expired tokens get distinct error from invalid signature.
4. **SQL injection impossible.** SQLAlchemy's parameterized queries prevent any injection even with malicious payloads.
5. **Unicode handling is flawless.** Korean, emoji, RTL, and very long strings all store and round-trip correctly.
6. **Reserved fields are properly inert.** All v1.1+ fields are NULL/default, no code branches read them.
7. **SDK mypy --strict passes.** No type errors.
8. **Server mypy --strict passes.** No type errors.

## Surprises / ambiguities

1. **PRD doesn't specify decision_type enum enforcement location.** Is it the server's job to reject invalid types, or should clients be trusted? PRD lists "approve, modify, escalate, reject" in a comment but doesn't say "MUST be one of these."

2. **PRD §4.3 says "cap interrupt payloads at 1MB" but doesn't specify WHERE to enforce.** SDK before submit? Server on ingest? Both? Current implementation: neither.

3. **PRD doesn't specify whether `ooo_active` is nullable or NOT NULL.** The SQL shows `BOOLEAN DEFAULT FALSE` without an explicit NOT NULL, but typical usage implies it should be NOT NULL with a default.

## Recommended action sequence

1. **Fix A-1 (Docker build)** — change `sdk/pyproject.toml` readme path. This unblocks all Docker-based testing.
2. **Fix A-2 (test flakiness)** — add a small sleep or use a shared engine for table creation in conftest.
3. **Add decision_type validation (C5-1)** — Literal["approve", "modify", "escalate", "reject"] in DecideRequest.
4. **Add payload size cap (C6-1)** — check len(json.dumps(payload)) > 1MB in POST /interrupts.
5. **Fix B-1 (ooo_active)** — add server_default and make nullable to match PRD.
6. **Add basic Playwright test for UI (A-3)** — at minimum verify page renders with a known payload.

## Tests added

- `scripts/verify_schema.py` — PRD §6.3 column-by-column schema verification
- `server/tests/integration/test_validation.py` — 19 validation tests covering C1–C7 scenarios
