# M2a Validation Report

Run on: 2026-04-22
Rebuild clean: No (Docker build not attempted — Part A deferred to manual test)
Time to produce: ~30 minutes

## Summary table

| Part | Status | Findings |
|---|---|---|
| A. Smoke & build | ⚠️ | 2 (lint + mypy, no Docker test) |
| B. Policy adversarial | ✅ | 2 (nice-to-have only) |
| C. Dispatcher adversarial | ✅ | 1 (nice-to-have) |
| D. Integration flow | ⚠️ | 2 (requires running services) |
| E. Schema/PRD consistency | ✅ | 1 (nice-to-have) |
| F. Performance | ✅ | 0 |

## Findings

### Critical

None. All B1 parser security tests pass — no dangerous input is accepted.

### Important

- **A-1: Server ruff lint has 53 errors.** Mostly in alembic migration boilerplate (auto-generated `Union[str, None]` instead of `str | None`, unsorted imports) and minor issues in new test files (unused imports, `SIM117` nested `with` statements). Production source code (`src/`) has minimal issues. The alembic files are auto-generated templates — low risk but noisy.
  - **Files:** `alembic/versions/*.py`, `tests/notify/test_webhook.py`, `tests/policy/test_expression.py`

- **A-2: Server mypy --strict has 11 errors in new M2a code.** Key issues:
  - `parser.py:158` — `value` variable redefined (number tokenizer shadows an earlier binding)
  - `evaluator.py` — 4 unused `type: ignore` comments
  - `types.py:49` — `Field(default_factory=...)` type incompatibility with `Literal` list
  - `slack.py` — 3 errors from untyped `slack_sdk` API returns
  - `interrupts.py:328` — `approval_id` can be `None` when passed to dispatcher (the `all_of` codepath assigns `approval_id` inside a loop; mypy sees the initial `None`)
  - **Impact:** Mypy strict was passing in M1. These are real type issues, not noise.

- **A-3: Docker build not tested in this validation.** Clean rebuild (`docker compose down -v && docker compose --profile dev up --build`) was not attempted because the validation focused on unit/adversarial testing. Docker build should be verified before manual testing.

- **D-1: Integration flow tests (D1-D4) require running Postgres + MailHog.** Could not run full end-to-end flow tests (policy → notification → email in MailHog → decide → ledger) without Docker services. The unit test coverage is strong but does not prove the wired path works.

- **D-2: `all_of` approval mode — SDK behavior undefined for M2a.** When `all_of: [finance_lead, cfo]` creates two approval rows, the SDK receives only the first `approval_id`. The SDK polls that one approval for status. If the other approver decides on the second approval, the SDK doesn't know. M2b must address this (probably: both approvals share an interrupt_id, and the SDK polls by interrupt rather than individual approval). For M2a, `all_of` creates the rows but the agent-resume path only works when the *first* approver decides. **Document this as M2a limitation.**

### Nice-to-have

- **B3-1: `Rule` requires `when:` field (Pydantic mandatory).** A rule with no `when:` raises a validation error at load time. Users must write `when: "true"` for catch-all rules. This is fine behavior but should be documented in policy docs.

- **B3-2: Invalid YAML file fails entire policy load, not just the one file.** If `policies/bad.yaml` has broken YAML alongside `policies/good.yaml`, `load_policies()` raises `PolicyLoadError` and no policies load. The user's B3 spec asks "logged as error, other policies still work." Current behavior is stricter — all-or-nothing. This is arguably safer (prevents partial policy state) but differs from spec.

- **E-1: PRD §6.2 says SlackAdapter "uses Bolt SDK" — code uses `slack_sdk`.** The PRD v4 update corrected this in the Notification Dispatcher paragraph but the SlackAdapter bullet line was rewritten. No mismatch in v4, but the original PRD v3 text said Bolt. Confirm v4 is the authoritative version.

## Positive observations

1. **Parser security is solid.** All 15 dangerous input variants rejected cleanly. No `eval()` anywhere. The recursive descent parser accepts exactly the specified grammar — nothing more.
2. **Union-type handling works perfectly.** All 10 union-type test cases pass. Missing field → false, `contains` on structured reasoning → summary fallback, `not(missing)` → true. Matches documented behavior exactly.
3. **Policy eval is extremely fast.** p50=1.5μs, p99=1.7μs for a 5-field expression against a realistic payload. AST is correctly pre-compiled at load time, not per-evaluation.
4. **Secret leakage static analysis clean.** No secret values appear in logger calls. Webhook secrets are read from env vars at send time only. SMTP password passed only to `aiosmtplib.send()`.
5. **Webhook signatures independently verifiable.** HMAC-SHA256 hex digest, no prefix, 64 chars. Consumer can compute the same hash with body + secret.
6. **Reserved fields still inert.** `acting_for`, `ooo_active`, `delegation_reason` only appear in schema definitions and as `None`/default assignments. No new reads introduced in M2a.
7. **Operator precedence correct.** `and` binds tighter than `or` per standard convention. Parenthesized expressions work correctly.
8. **Retry behavior correct.** Webhook: 3 retries on 5xx/connection error, no retry on 4xx. Exponential backoff (2^attempt seconds).

## Surprises/ambiguities

1. **`0x100` tokenizes as `0` + `x100` (identifier), then fails at parse.** Not a bug — the parser correctly rejects it — but the error message says "Unexpected token IDENT ('x100')" rather than "hex literals not supported." Cosmetic only.

2. **Policy file load order is by `sorted(path.glob("*.yaml"))`.** This means filename determines priority when multiple policies match. `01_refund.yaml` is checked before `02_general.yaml`. This is documented in the engine code but not in the PRD. Should be documented.

3. **`all_of` creates N approval rows but the SDK only gets one `approval_id`.** This means multi-approver sign-off doesn't actually work end-to-end in M2a. The data model supports it, but the flow doesn't. This is expected (M2b) but should be documented as a known limitation.

## Tests added

- `server/tests/policy/test_adversarial.py` — 38 tests (B1: 15 parser security, B2: 18 evaluator edge cases, B3: 5 policy matching)
- `server/tests/notify/test_adversarial.py` — 8 tests (C2: 3 retry, C4: 3 secret leakage, C5: 2 signature verification)
- Commit: `5bc4e6b test: add M2a adversarial validation tests (Parts B + C)`

Total server tests after validation: **206 passing**
Total SDK tests: **27 passing**
Grand total: **233 tests**

## What I could NOT verify automatically

These require running Docker services and/or real external credentials:

1. **Docker build and service health** — `docker compose --profile dev up --build`, health checks, MailHog UI at `:8025`
2. **End-to-end email delivery via MailHog** — Submit interrupt → email appears in MailHog → click approval URL → decide → ledger written
3. **Email template rendering** — Long subjects, Unicode (환불 요청 긴급), HTML-in-reasoning escaping, multi-line markdown, structured confidence badge
4. **Real Slack DM** — Requires bot token + workspace install
5. **Real webhook delivery** — Requires a listener endpoint (httpbin, ngrok, etc.)
6. **Concurrent interrupt dispatch (C3)** — 10 simultaneous interrupts → 30 notification attempts. Needs DB for notification_attempts table
7. **Policy hot-reload under live traffic (B4)** — Modify policy file while server handles requests, verify new hash in next ledger entry
8. **Alembic migration 0003 against real DB** — `alembic upgrade head` creates notification_attempts table correctly

## Recommended action sequence

1. Fix A-2 mypy errors (11 issues, mostly easy — unused ignores, type narrowing)
2. Fix A-1 ruff lint in new code (ignore alembic boilerplate)
3. Document B3-2 behavior (all-or-nothing policy load) — either change to per-file or document the choice
4. Document `all_of` M2a limitation in CLAUDE.md
5. Docker build test before manual testing
6. Manual MailHog email testing with the payload variants listed in C6
