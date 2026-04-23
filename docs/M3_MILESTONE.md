# M3 Milestone Plan — Security, Ledger, and Audit

**Target**: End of week 8
**Release**: v0.2.0
**Prerequisite**: M2 complete (M1+M2a+M2b+M2c)

---

## Overview

M3 transforms Deliberate from a functional prototype into a production-grade system. The three sub-milestones address:

- **M3a (Security)**: Close the security gaps that make the current system unsuitable for real deployments — unsigned URLs, anonymous approvers, race conditions.
- **M3b (Ledger)**: Deliver the audit capabilities promised by the product's core value proposition — immutable records, queryable history, export.
- **M3c (DX + Release)**: Polish developer experience and ship v0.2.0.

---

## M3a — Security and Identity

### M3a-1: Wire signed JWT approval tokens into URLs

**Priority**: Critical
**Effort**: Low (2-3 hours)
**Why**: Every approval URL currently exposes the raw UUID. Any UUID holder can access any approval. The signing functions already exist in `server/src/deliberate_server/auth.py:24-55`.

**Implementation**:
1. In `interrupts.py`, call `create_approval_token(approval_id)` when generating the approval URL
2. Change UI route from `/a/[approval_id]` to `/a/[token]`
3. In the approval page, decode the JWT to extract `approval_id`, then fetch payload
4. Update SDK `client.py` to handle token-based URLs in `InterruptResult`
5. Tokens default to 7-day expiry, configurable per policy rule

**Files**: `interrupts.py`, `auth.py`, `page.tsx`, `client.py`

**Acceptance criteria**:
- Approval URLs contain a JWT token, not a raw UUID
- Expired tokens show "Link expired" page
- Invalid tokens show "Invalid link" page
- Existing tests updated to use token-based URLs

---

### M3a-2: Approver identity via magic link

**Priority**: Critical
**Effort**: Medium (1-2 days)
**Why**: Every decision currently records `anonymous@deliberate.dev` as the approver email. This makes the entire ledger audit trail meaningless.

**Implementation**:
1. New endpoint: `POST /auth/magic-link` — sends a magic link email to the policy-assigned approver
2. Magic link contains a short-lived JWT (15min) with the approver's email
3. On click, set an HTTP-only session cookie (7-day expiry) with `approver_email`
4. `POST /approvals/{id}/decide` validates the cookie's email matches the policy-assigned approver
5. `DecisionForm` reads the email from a `/auth/me` endpoint instead of hardcoding

**Files**: New `auth_routes.py`, `decision-form.tsx`, `approvals.py`

**Acceptance criteria**:
- First visit to approval URL redirects to magic link flow if no session cookie
- Decision submission rejected if approver email doesn't match policy assignment
- Ledger entries record the real approver email
- Session cookie is HTTP-only, secure, SameSite=Lax

---

### M3a-3: FOR UPDATE lock on decide endpoint

**Priority**: High
**Effort**: Low (30 minutes)
**Why**: Two concurrent decision submissions can both see `status='pending'` and both proceed. The worker already uses FOR UPDATE; the decide endpoint should too.

**Implementation**:
- `approvals.py:129` — change `session.get(Approval, approval_id)` to `session.get(Approval, approval_id, with_for_update=True)`

**Acceptance criteria**:
- Concurrent decision submissions: only the first succeeds, second gets 409
- Add a test that simulates concurrent decide requests

---

### M3a-4: Escalation depth guard

**Priority**: Medium
**Effort**: Low (1-2 hours)
**Why**: A policy with circular `escalate_to` creates infinite approval chains.

**Implementation**:
- In `worker.py:_process_timeout_escalate`, query the escalation chain depth by following `escalated_to` FKs
- If depth >= `MAX_ESCALATION_DEPTH` (configurable, default 3), fall back to `on_timeout=fail`
- Log a warning when the max depth is reached

**Acceptance criteria**:
- Escalation stops at configured max depth
- Test: 3 nested escalations, 4th falls back to fail

---

### M3a-5: Key derivation for signing

**Priority**: Medium
**Effort**: Low (1 day)
**Why**: A single `SECRET_KEY` is used for JWT signing, HMAC signatures, content hashing, and decision signing. Key compromise exposes everything.

**Implementation**:
- Use HKDF (from `cryptography` package) to derive purpose-specific keys from `SECRET_KEY`
- Contexts: `jwt-signing`, `hmac-webhook`, `content-hash`, `decision-signature`
- Backward-compatible: detect old signatures and log deprecation warnings

**Acceptance criteria**:
- Each signing operation uses a derived key
- Old signatures still verify (migration path)
- New signatures use derived keys

---

## M3b — Ledger and Audit

### M3b-1: Fix resume ACK immutability violation

**Priority**: High
**Effort**: Medium (1 day)
**Why**: `POST /approvals/{id}/resume-ack` currently mutates `ledger_entries.content` in place, violating the "append-only, immutable" invariant from PRD §5.3.

**Implementation**:
- New `resume_events` table: `id`, `ledger_entry_id`, `resume_status`, `resume_latency_ms`, `created_at`
- `resume-ack` writes to `resume_events` instead of mutating `ledger_entries.content`
- Ledger query joins `resume_events` when returning results
- Migration: backfill existing `resume` data from `ledger_entries.content` into `resume_events`

**Acceptance criteria**:
- `ledger_entries.content` is never mutated after initial write
- `content_hash` remains valid for the lifetime of the entry
- Resume data accessible via ledger query

---

### M3b-2: Enhanced ledger query

**Priority**: High
**Effort**: Medium (1 day)
**Why**: Current ledger query only filters by `thread_id`. PRD §6.2 requires approver, date range, and text search.

**Implementation**:
- Add query params: `approver_email`, `from_date`, `to_date`, `search` (rationale text), `limit`, `cursor`
- Use JSONB path queries for `approver_email` and `rationale_notes`
- Cursor-based pagination using `created_at` + `id` composite cursor
- Index: `idx_ledger_approver` on `content->>'approval'->>'approver_email'`

**Acceptance criteria**:
- Filter by approver_email returns only that approver's decisions
- Date range filtering works with ISO 8601 dates
- Cursor pagination returns consistent results across pages
- Performance: <100ms for 10k ledger entries

---

### M3b-3: JSON and CSV export

**Priority**: High
**Effort**: Medium (1 day)
**Why**: PRD M3 explicit. Auditors need to export records to spreadsheets and compliance tools.

**Implementation**:
- `GET /ledger/export?format=json` — returns all matching entries as JSON array (streaming for large sets)
- `GET /ledger/export?format=csv` — flattens JSONB content into columns, returns CSV with Content-Disposition header
- Same filter params as enhanced ledger query
- Streaming response for large exports (>1000 entries)

**Acceptance criteria**:
- JSON export matches ledger query response shape
- CSV has flat columns: `id`, `created_at`, `thread_id`, `approver_email`, `decision_type`, `rationale_category`, `rationale_notes`
- Export respects filter params
- Streaming works for 10k+ entries without OOM

---

### M3b-4: Unified audit view in UI

**Priority**: High
**Effort**: High (2-3 days)
**Why**: PRD §4.2 states layouts render in both decision and audit modes. Currently only decision mode exists.

**Implementation**:
- When `status !== 'pending'`, fetch the decision record alongside the payload
- Pass both to the layout component
- Each layout renders the decision overlay: who decided, when, decision type, rationale, duration
- Read-only mode: no DecisionForm, decision details displayed instead
- Timeline view: show interrupt → notification → decision → resume events chronologically

**Acceptance criteria**:
- Decided approvals show the layout with decision overlay
- Timed-out approvals show the layout with timeout information
- Escalated approvals show the chain: original → escalated → decided
- All three layouts support audit mode

---

### M3b-5: Chained ledger hashes

**Priority**: Medium
**Effort**: Medium (1 day)
**Why**: Makes the append-only log tamper-evident. PRD §6.6 deferred to M3.

**Implementation**:
- Add `prev_hash` column to `ledger_entries` (nullable, null for first entry per application)
- On write, query the most recent entry's `content_hash` and set as `prev_hash`
- Include `prev_hash` in `content` before computing `content_hash` (chain integrity)
- Verification endpoint: `GET /ledger/verify?application_id=...` — walks the chain, reports any breaks

**Acceptance criteria**:
- Every new ledger entry references the previous entry's hash
- Chain verification endpoint detects tampering (modified content_hash)
- Migration handles existing entries (first entry after migration has prev_hash=null)

---

## M3c — Developer Experience and Release

### M3c-1: Fix DecisionForm API URL

**Priority**: Medium
**Effort**: Low (1 hour)
**Why**: `window.location.hostname:4000` breaks behind reverse proxies and non-standard ports.

**Implementation**:
- Use `NEXT_PUBLIC_API_URL` environment variable
- Fallback: add `next.config.js` rewrite rule `/api/:path*` → `http://server:4000/:path*`
- DecisionForm uses relative `/api/approvals/...` path

---

### M3c-2: Extract shared AgentReasoningSection

**Priority**: Low
**Effort**: Low (1 hour)
**Why**: Three layouts duplicate the same component. DRY.

**Implementation**:
- Create `ui/components/shared/agent-reasoning.tsx`
- Import in all three layouts

---

### M3c-3: CONTRIBUTING.md

**Priority**: Medium
**Effort**: Low (2 hours)
**Why**: PRD M3 explicit. Needed for community contributions.

**Implementation**:
- Development setup guide
- Code style and testing expectations
- PR process
- Label 5-10 GitHub issues as `good-first-issue`

---

### M3c-4: Release v0.2.0

**Priority**: High
**Effort**: Medium (1 day)
**Why**: First public release. Makes the project available to the community.

**Implementation**:
- SDK: Verify `pyproject.toml` metadata, `uv build`, publish to PyPI as `deliberate-sdk`
- Server: Build and push Docker images to Docker Hub (`deliberate/server:0.2.0`, `deliberate/server:latest`)
- UI: Build and push Docker image (`deliberate/ui:0.2.0`, `deliberate/ui:latest`)
- GitHub release with changelog
- Announcement: LangGraph Discord, Reddit r/LangChain, Hacker News "Show HN"

---

## Dependency Graph

```
M3a-1 (signed tokens) ──┐
M3a-2 (magic link) ─────┤
M3a-3 (FOR UPDATE) ─────┤
M3a-4 (escalation guard)┤
M3a-5 (key derivation) ─┘
         │
         ▼
M3b-1 (resume immutability) ──┐
M3b-2 (enhanced query) ───────┤
M3b-3 (export) ───────────────┤ (depends on M3b-2)
M3b-4 (audit view) ───────────┤ (depends on M3a-1, M3a-2)
M3b-5 (chained hashes) ───────┘ (depends on M3b-1)
         │
         ▼
M3c-1 (API URL fix) ──────────┐
M3c-2 (shared component) ─────┤
M3c-3 (CONTRIBUTING.md) ──────┤
M3c-4 (release v0.2.0) ───────┘ (depends on all M3a + M3b)
```

## Test Count Target

- Current: 248 tests (218 server + 30 SDK)
- M3 target: ~320 tests (+30 security, +25 ledger, +15 audit view, +2 misc)

## Known Items Deferred to M4

- Google/GitHub OAuth for approvers (magic link sufficient for v0.2.0)
- Three additional layouts (data_access, content_moderation, code_deployment)
- Custom layout SDK
- OTLP export for ledger
- True LangGraph `interrupt()` / `Command(resume=...)` integration
- `deliberate-core` package extraction
- Slack inline approval
- O(1) API key lookup (indexed hash column)
