# Deliberate — Product Requirements Document

**Status**: Draft v4 · Pre-1.0 scope
**Last updated**: April 2026
**Owner**: Beomwoo Kang

**Changelog**
- v4 (Apr 2026): Notification adapter details formalized (email/SMTP, webhook/HMAC, Slack DM). Added `notify` field to policy rule schema and `notification_attempts` operational table. Expression evaluator semantics for missing field access and union-type payloads documented. Webhook configuration via `webhooks.yaml`. M2a implementation begins.
- v3 (Apr 2026): Schema extension for agent_reasoning (structured variant), confidence field added to interrupt payload, audit-mode rendering added to roadmap. Based on M1 human validation findings.
- v2 (Apr 2026): Five deferred design decisions resolved — Slack UX, delegation, ledger-as-truth, tenant model, LangGraph version support. Schema and data model updated to accommodate near-term additions without migration.

---

## 0. One-liner

The approval layer for LangGraph agents. Notifications, timeouts, structured audit, and approver-facing UIs for the humans who sign off on agent decisions.

---

## 1. Background and motivation

### 1.1 What LangGraph shipped

In early 2025, LangGraph introduced `interrupt()` as a first-class primitive for human-in-the-loop workflows. Call `interrupt()` inside a graph node, and execution pauses. State is persisted to a checkpointer. Later, `Command(resume=value)` picks execution back up from the same point. This is a clean runtime abstraction for the "pause and wait for a human" pattern, and it's a significant improvement over duct-taping it yourself.

LangGraph's blog post on `interrupt()` was explicit that this was designed for *interactive, same-session* HITL. The classic example: an approval gate in a chatbot or a Streamlit app, where the user types the decision back immediately.

### 1.2 The gap that's still open

The runtime primitive handles the *pause* and the *resume*. It intentionally leaves unaddressed everything in between, for good reason — those pieces depend on organizational context LangGraph can't know. Specifically:

**Notification.** When a thread enters the interrupted state, no one is told. The thread sits in the checkpointer marked `interrupted`. If the person who needs to decide isn't watching the terminal or polling the thread state themselves, they don't know you're waiting.

**Timeout and escalation.** A thread paused 30 seconds ago and a thread paused 3 weeks ago are indistinguishable. There's no "escalate to backup approver after 4h" or "fail gracefully after 24h." Teams build cron jobs that poll for stale interrupted threads, which is non-trivial infrastructure when done correctly (retry logic, fallback routing, programmatic resume).

**Audit log.** LangGraph's persistence records graph state — sufficient for debugging and resumability, insufficient as a business record. It doesn't produce a structured log of *who was asked, when they responded, what they decided, and why*. For most production use cases, and certainly for EU AI Act Article 14 compliance, NIST AI RMF, and SOC 2, teams need a human-readable, exportable record of every human decision made against an agent's recommendation.

**Approver interface.** The only interface LangGraph gives the approver is `Command(resume=...)` called from Python. But most approvers in real agent deployments — finance leads approving refunds, legal reviewers signing off contracts, audit partners closing procedures — are not Python users. Engineering teams end up building one-off approval dashboards or Slack buttons. These are repeated work, usually incomplete, and rarely match what the approver actually needs to make a good decision.

### 1.3 How other tools relate

Several products address parts of this gap, but with different primary concerns:

- **Permit.io** approaches HITL as an extension of authorization. Its MCP server exposes approval tools to LLMs, gated by policy. Strong fit when access control is the core problem. Less focused on the approver's decision experience itself.
- **Handover** is a commercial SaaS that adds out-of-band approval (email notifications, timeouts, logs) to LangGraph. Not open source, and the approver UI is generic across all use cases.
- **Langfuse** and **Phoenix** are observability platforms that can record human feedback as annotations on traces. Complementary to Deliberate — they record what the agent did; Deliberate records what the human decided. Ledger export to OTLP is on the roadmap specifically to close this loop.
- **Agent-framework-native HITL** (CrewAI's task approval, AutoGen's UserProxyAgent) solves the in-session case but doesn't extend beyond the running process.

None of these are built around a core thesis that the approver — typically a non-engineer in a regulated or high-stakes function — is the primary user whose experience determines whether HITL actually works in production. Deliberate is.

### 1.4 Thesis

**HITL succeeds or fails at the approval screen.** Everything upstream (notification, policy, timeout) is scaffolding. Everything downstream (audit, export, observability) is consequence. The approver's 30-second experience is where automation becomes accountability — and it's the part current tooling invests in least.

Deliberate is an opinionated take on that experience, wrapped in the infrastructure that makes it production-viable.

---

## 2. Goals and non-goals

### 2.1 Goals (v1.0)

1. **Drop-in integration with LangGraph.** Two lines of code (decorator + interrupt payload) to convert a LangGraph node into a routed, logged, human-approved step.
2. **First-class approver UI.** Built-in layouts for at least three HITL-critical domains, mobile-first, designed for 30-second decisions.
3. **Multi-channel notification.** Slack, Email, and Webhook out of the box. SMTP-based email requires no third-party partnership.
4. **Declarative routing.** YAML policies resolve approvers, timeouts, and escalation from interrupt payload.
5. **Structured audit ledger.** Every decision captured with who/when/why/context, queryable and exportable.
6. **Self-hostable in under 5 minutes.** Docker Compose one-liner, no external dependencies beyond standard Postgres.

### 2.2 Non-goals (v1.0)

- **Non-LangGraph framework support.** We will resist the temptation to be a generic "agent approval layer." Depth over breadth. Post-1.0 we can reconsider CrewAI/AutoGen, but only if the LangGraph experience is genuinely excellent first.
- **Identity and SSO.** v1 ships with email-based magic links and optional OAuth (Google, GitHub). SAML/enterprise SSO is post-1.0.
- **Multi-step workflows.** Deliberate handles single-decision gates. Multi-step approval chains ("A approves, then B approves, then C signs off") are a BPMN-engine class of problem. Use Camunda or Temporal if that's what you need.
- **Managed cloud.** Self-host only for v1. Managed offering only after open-source adoption proves demand.
- **Full policy expression language.** Policies are conditional + approver + timeout. No Rego, no CEL. If users need more, they're likely using the wrong tool.

### 2.3 Success signals

For a pre-1.0 open source project, we care about:

- **Installation completion rate.** What percentage of people who `docker compose up` successfully make their first approval round-trip within 15 minutes? Target: >60%.
- **Decision-to-resume latency.** How fast does a submitted approval actually resume the LangGraph thread? Target: <500ms p95.
- **Approver return usage.** Do approvers come back for a second decision via the link, or do they bounce? Measured in self-reported deployments.
- **GitHub signals.** Stars, forks, and meaningful issues (not "how do I install" but "here's a design constraint you missed"). These indicate the project is being used, not just bookmarked.

---

## 3. User personas and scenarios

### 3.1 Personas

**The integrator (engineer).** Python developer who builds LangGraph agents. Cares about: how fast they can get an approval loop working, how clean the SDK is, how well it fits their existing stack. Lives in code.

**The approver (non-engineer).** Finance lead, legal reviewer, audit partner, DPO, compliance officer, content editor. Cares about: understanding the decision quickly, making it confidently, getting back to their main job. Lives in Slack, email, and their phone.

**The operator (engineer or SRE).** Whoever deploys and maintains Deliberate. Cares about: the system not breaking, migrations being safe, logs being useful, rollbacks being straightforward.

**The auditor (compliance, legal, or external).** Reviews decisions after the fact. Cares about: finding every decision related to a given agent/policy/customer, reconstructing context, exporting to compliance formats.

### 3.2 Core scenarios

**Scenario A — Refund approval.** An e-commerce company runs a customer support agent on LangGraph. When a refund over $500 is requested, the agent pauses. Finance lead Priya gets a Slack DM, opens the approval page on her phone during a meeting, sees the customer history and the agent's reasoning, approves with a structured reason, and goes back to the meeting. Total elapsed time: 30 seconds. The agent resumes and processes the refund. Ledger records the full context for the next SOC 2 audit.

**Scenario B — Contract redline review.** A legal-ops agent drafts contract amendments. When a liability cap change is proposed, the agent pauses. Legal counsel Marcus gets an email with a link. The approval page shows the full diff, highlights the three clauses the agent flagged as novel, and lets him approve, redline, or reject with reason. The rationale he provides becomes part of the contract's audit trail.

**Scenario C — Audit procedure sign-off.** A financial audit agent (e.g., for a firm using Fieldguide-style tooling) completes substantive testing on revenue cut-off for a client. Before marking the procedure complete, the agent pauses. Audit partner Yuki gets notified, reviews the checklist of tests performed, sees the two flagged exceptions with evidence references, signs off on one and requests additional testing for the other. The sign-off is bound to her identity for the engagement workpapers.

**Scenario D — Agent-initiated escalation.** A data-processing agent detects an anomaly it's not confident about. It calls `interrupt()` with a specific `layout="anomaly_review"` and evidence. Deliberate routes to the on-call data team. No one responds within 2 hours. Policy escalates to the data team lead. She approves the agent's recommendation, which resumes the pipeline.

---

## 4. Product scope

### 4.1 Functional scope (v1.0)

| Area | In scope | Deferred |
|---|---|---|
| Integration | LangGraph `@approval_gate` decorator, interrupt payload capture, resume on decision | Other frameworks |
| Notifications | Slack app, SMTP email, generic Webhook | Teams, Telegram, SMS |
| Approver UI | 3 built-in layouts (financial, document, procedure), mobile-first, structured rationale | 3 additional layouts (data_access, content_moderation, code_deployment), custom layout SDK |
| Routing | YAML policy with conditional approvers, timeout, escalation | Complex expression language, multi-step chains |
| Ledger | Postgres-backed, JSON export, signed entries | OTLP/Langfuse export, tamper-evident log chain |
| Auth | Email magic link, optional Google/GitHub OAuth | SAML, enterprise SSO, RBAC |
| Deployment | Docker Compose, single-node | Kubernetes Helm chart, multi-region |
| Observability | Basic operational metrics (Prometheus), structured logs | Built-in dashboards |

### 4.2 Built-in layouts

Layouts are opinionated information architectures for common approval contexts. Each layout is a React component that consumes a typed payload schema. v1 ships three; three more in v1.1.

**`financial_decision`** — For refunds, expense approvals, budget requests, discount approvals. Emphasizes amount, customer context, and evidence. Decision actions: approve / approve with change / request more / reject. Structured rationale chips tuned to financial use cases (product issue, retention, policy exception, custom).

**`document_review`** — For contract redlines, policy approvals, content sign-offs that are text-heavy. Emphasizes the document itself and the specific clauses the agent flagged. Decision actions: approve / redline / reject. Supports diff view and clause-level commenting.

**`procedure_signoff`** — For audit procedures, compliance checks, quality gates. Emphasizes a checklist of completed steps, flagged exceptions with evidence references, and standards reference. Decision actions: sign off / request rework / escalate. Supports linking to external standards documentation.

Layouts render in both decision and audit modes. Before a decision is made, the layout shows the decision form. After, the same layout shows the decision record — who decided, when, with what rationale, against the original context. This symmetry means auditors and approvers see the same information architecture, just with different affordances. v1 focuses on the decision mode; unified audit view is scoped to M3.

### 4.3 Out of scope explicitly

- Building our own LLM-based decision assistance. Deliberate presents what the agent provides; it does not re-reason about the decision.
- Storing or proxying the content of interrupt payloads that exceed 1MB. Deliberate is a decision-routing system, not a document store. Links out to S3 or similar for heavy artifacts.
- Being a general workflow orchestrator. If you're using Deliberate for things that aren't human approval of agent decisions, we've probably mis-scoped the product.

---

## 5. Core schemas (the three contracts)

The system is pinned down by three schemas. Everything else is implementation. These are the API boundaries the project commits to for v1.

### 5.1 Interrupt payload

What the SDK captures when a LangGraph node calls `interrupt()` inside an `@approval_gate`.

```python
{
  "layout": "financial_decision",           # Required. Layout identifier.
  "subject": "Refund for customer #4821",   # Required. One-line header.
  "amount": { "value": 750.00, "currency": "USD" },  # Layout-specific fields
  "customer": {
    "id": "cust_4821",
    "display_name": "Maya Chen",
    "tenure": "18 months",
  },
  "agent_reasoning": "Customer reported persistent dashboard loading issues for 3 weeks. Support tickets #4821, #4856 confirm engineering acknowledged the bug...",
  // OR structured form (union type — string or object):
  // "agent_reasoning": {
  //   "summary": "Refund supported by product issue and customer tenure.",
  //   "points": [
  //     "Customer reported dashboard loading issues for 3 weeks",
  //     "Engineering confirmed the bug (tickets #4821, #4856)",
  //     "Customer requested refund for remaining 5 months",
  //     "No prior refund history"
  //   ],
  //   "confidence": "high"   // Optional: "high" | "medium" | "low"
  // },
  "evidence": [
    {"type": "ticket", "id": "#4821", "summary": "Bug confirmed", "url": "https://support.../4821"},
    {"type": "ticket", "id": "#4856", "summary": "Escalation", "url": "https://support.../4856"},
    {"type": "history", "summary": "No prior refunds", "url": null},
  ],
  "decision_options": [  # Optional. Defaults provided by layout.
    {"type": "approve", "label": "Approve as-is"},
    {"type": "modify", "label": "Approve with change", "fields": ["amount"]},
    {"type": "escalate", "label": "Request more info"},
    {"type": "reject", "label": "Reject"},
  ],
  "rationale_categories": [  # Optional. Defaults provided by layout.
    "product_issue", "retention", "policy_exception", "other"
  ],
  "metadata": {              # Passed through to ledger unchanged
    "thread_id": "langgraph-thread-abc123",
    "trace_id": "trace-xyz789",
    "agent_version": "v1.2.0",
  }
}
```

Core principle: the payload is everything an approver needs to decide, plus everything a future auditor needs to understand the context. Agent-level data (reasoning, evidence) and decision mechanics (options, rationale categories) are first-class; the graph-level metadata is pass-through.

For reasoning complex enough to benefit from structure, use the object form of agent_reasoning — the UI will render points[] as a list and may use confidence to flag low-evidence decisions.

Reasoning can be string or structured. For short reasoning, a single string remains fine. For complex decisions, a structured variant with summary, points[], and optional confidence produces better readability. UI layouts render both forms; agents choose what fits their output. This addition came from M1 manual validation where multi-sentence string reasoning showed readability issues on mobile.

### 5.2 Policy (YAML)

How Deliberate routes an interrupt to approvers.

```yaml
# policies/refund.yaml
name: refund_approval
matches:
  layout: financial_decision
  subject_contains: "Refund"

rules:
  # Auto-approve below threshold — no human needed
  - name: auto_approve_small
    when: "amount.value < 100"
    action: auto_approve
    rationale: "Below $100 threshold, policy §3.1"

  # Standard amount, any finance team member
  - name: standard
    when: "amount.value >= 100 and amount.value < 5000"
    approvers:
      any_of: [finance_team]    # Group defined elsewhere
      backup_delegate: finance_lead    # v1.1+: auto-route if primary is OOO
    timeout: 4h
    on_timeout: escalate
    escalate_to: finance_lead
    notify: [email, slack]             # Channels to notify approvers through

  # High value, two-person approval
  - name: high_value
    when: "amount.value >= 5000"
    approvers:
      all_of: [finance_lead, cfo]
    timeout: 8h
    on_timeout: fail
    require_rationale: true
    notify: [email, slack, webhook]    # Fan out to all three channels
```

Evaluation is top-to-bottom, first match wins. Expression language is intentionally minimal: comparison operators (`<`, `>`, `<=`, `>=`, `==`, `!=`), boolean (`and`, `or`, `not`), field access via dot notation, `contains` for string membership. No function calls, no loops. If a rule's condition needs more than this, the interrupt payload should be pre-processed by the agent.

**Expression evaluator semantics.** Missing field access (e.g., a dotted path that doesn't resolve to a value in the payload) evaluates to a rule-matching `false` rather than raising an error, allowing policies to work unchanged across payload variants. This is important because some payload fields are union types — for example, `agent_reasoning` may be a plain string or a structured `{summary, points[], confidence?}` object. Concretely:

- `when: "agent_reasoning.confidence == 'low'"` — if `agent_reasoning` is a string (no `.confidence`), the expression evaluates to `false`. The rule doesn't match; evaluation continues to the next rule.
- `when: "agent_reasoning contains 'fraud'"` — if `agent_reasoning` is a string, standard string `contains`. If it's the structured object, `contains` applies to the `summary` field as a fallback.
- Any other dotted path that doesn't resolve → `false`, not exception.

**Notification channels.** Each rule may include a `notify` field specifying which channels to use: `email`, `slack`, `webhook`, or any combination. When `webhook` is specified, all active webhooks defined in `/config/webhooks.yaml` fire (fan-out). If `notify` is omitted, the default is `[email]`. Auto-approve rules do not fire notifications.

```yaml
# /config/webhooks.yaml
webhooks:
  - id: teams_integration
    url: https://hooks.office.com/webhook/...
    secret_env: TEAMS_WEBHOOK_SECRET   # Secret read from this env var at runtime
    active: true
  - id: pagerduty
    url: https://events.pagerduty.com/...
    secret_env: PAGERDUTY_WEBHOOK_SECRET
    active: false                       # Disabled — won't receive notifications
```

Groups and individual approvers are resolved separately via `deliberate/config/approvers.yaml` — kept separate so policies can be versioned in source control without leaking personal data.

**Delegation (schema-reserved for v1.1+).** The `backup_delegate` field is accepted in the policy schema from v1.0 but is a no-op until v1.1, when the out-of-office delegation feature ships. Reserving the field in v1.0 means users can version-control policies with delegation intent already expressed, and no schema migration is needed when the feature activates. Approver directories (`approvers.yaml`) also reserve an `out_of_office` block per approver for the same reason:

```yaml
# approvers.yaml
- id: finance_lead
  email: priya@acme.com
  out_of_office:       # Schema-reserved, inert until v1.1
    active: false
    from: null
    until: null
    delegate_to: null
```

Broader delegation patterns (conditional delegation, delegation chains, role-based delegation) are deferred to v2.0+ and will arrive alongside a proper auth/RBAC feature. The policy schema will extend, not replace, the v1.1 fields.

### 5.3 Ledger entry

The structured record written when an approval decision completes. **The ledger entry is the canonical business record — all other tables in Deliberate's database are operational projections of this content.** This decision is explained in §6.5.

```json
{
  "id": "ledger_01HGQ3...",
  "created_at": "2026-04-18T14:23:11.472Z",
  "thread_id": "langgraph-thread-abc123",
  "trace_id": "trace-xyz789",
  "application_id": "app_prod_refund_agent",   // Reserved: see §6.5 on tenant model

  "interrupt": { /* full original payload */ },
  "policy_evaluation": {
    "matched_rule": "standard",
    "policy_name": "refund_approval",
    "policy_version_hash": "sha256:a1b2c3..."
  },

  "approval": {
    "approver_id": "user_priya_finance",
    "approver_email": "priya@acme.com",
    "acting_for": null,                    // Reserved for v1.1+: populated when this is a delegated decision
    "decided_at": "2026-04-18T14:24:03.201Z",
    "decision_type": "approve",
    "decision_payload": { /* e.g. modified amount */ },
    "rationale_category": "product_issue",
    "rationale_notes": "Bug confirmed by eng, one-time policy exception approved",
    "channel": "slack",                    // Which channel notified
    "decided_via": "web_ui",               // web_ui, api, slack_inline, email
    "review_duration_ms": 52000
  },

  "escalations": [],                       // If any
  "resume": {
    "resumed_at": "2026-04-18T14:24:03.847Z",
    "resume_latency_ms": 646,
    "resume_status": "success"
  },

  "content_hash": "sha256:...",            // SHA-256 of all preceding fields
  "signature": "..."                       // Server signature over content_hash
}
```

Entries are append-only and immutable once written. Corrections (e.g., an approver's email changing organization-wide) never mutate existing entries — a new entry referencing the original is added, preserving the historical truth of what was recorded at the time of decision. This is the concrete implementation of "ledger as source of truth."

**Reserved fields.** `application_id` and `approval.acting_for` are present in the schema from v1.0 but are populated with placeholder values (`"default"` and `null` respectively) until the tenant model and delegation features activate. This is deliberate: ledger entries written today will remain queryable and correctly shaped when those features ship, without migration.

---

## 6. Technical architecture

### 6.1 System overview

```
┌─────────────────────────────────────────────────────────────┐
│                    User's LangGraph agent                   │
│                                                             │
│   @approval_gate(layout="financial_decision", policy=...)   │
│   def refund_node(state):                                   │
│       return interrupt({...})                               │
│                                                             │
│   LangGraph checkpointer (Postgres/SQLite — user-managed)   │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Deliberate Server                        │
│                                                             │
│   ┌───────────────┐   ┌────────────────┐   ┌─────────────┐ │
│   │  API Gateway  │──▶│ Policy Engine  │──▶│ Notification│ │
│   │   (FastAPI)   │   │ (YAML eval.)   │   │  Dispatcher │ │
│   └───────┬───────┘   └────────────────┘   └──────┬──────┘ │
│           │                                        │       │
│           ▼                                        ▼       │
│   ┌───────────────┐                      ┌────────────────┐│
│   │  Ledger Store │                      │  Approval UI   ││
│   │  (Postgres)   │                      │ (Next.js)      ││
│   └───────┬───────┘                      └────────┬───────┘│
│           │                                       │        │
│           └──────────────┬────────────────────────┘        │
│                          │                                 │
│                          ▼                                 │
│                 ┌─────────────────┐                        │
│                 │  Timeout Worker │                        │
│                 │   (APScheduler) │                        │
│                 └─────────────────┘                        │
└────────────────────────┬────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┬───────────────┐
          ▼              ▼              ▼               ▼
      ┌────────┐    ┌────────┐    ┌──────────┐    ┌──────────┐
      │ Slack  │    │  SMTP  │    │ Webhook  │    │ Approver │
      │  App   │    │ Server │    │   POST   │    │ (Human)  │
      └────────┘    └────────┘    └──────────┘    └──────────┘
```

### 6.2 Components

**Python SDK (`deliberate` on PyPI).** Thin wrapper. The `@approval_gate` decorator registers with the node, intercepts the `interrupt()` call, sends payload to server, subscribes to resume signal, and calls `Command(resume=...)` when the decision arrives. SDK does not need to be long-running — it's request/response from the user's agent's perspective, with LangGraph's own checkpointer holding state during the wait.

**API Gateway (FastAPI, Python).** Single entry for:
- `POST /interrupts` — agent submits a new interrupt
- `GET /approvals/{token}` — approver opens the approval page (renders Next.js app)
- `POST /approvals/{id}/decide` — approver submits decision
- `GET /ledger/...` — ledger query and export
- `GET /health`, metrics endpoints

**Policy Engine.** Loads YAML policies from a configured directory (hot-reloaded). On each incoming interrupt, evaluates rules top-to-bottom against the payload. Returns a resolved plan: approvers, channels, timeout, escalation target.

Expression evaluator is a small purpose-built parser (not eval'd Python, not a general expression language). This is deliberate — keeps the surface area small and auditable, and makes it obvious to users what's supported.

**Notification Dispatcher.** Takes a resolved plan and fires notifications in parallel (`asyncio.gather`). Each channel is a pluggable adapter implementing a common `Notifier` protocol (open for third-party extension post-1.0):
- **EmailAdapter** — uses `aiosmtplib` for async SMTP. HTML template includes subject, evidence preview, and a "Review and decide" button. Plain-text fallback included. Retries 3x with backoff on connection failure; fails immediately on auth error.
- **WebhookAdapter** — POSTs a signed JSON payload (`X-Deliberate-Signature: HMAC-SHA256`) to every active webhook in `/config/webhooks.yaml`. Retries 3x with exponential backoff on 5xx; no retry on 4xx. Timeout: 10s per request.
- **SlackAdapter** — uses `slack_sdk` (not Bolt). Looks up Slack user by approver email via `users.lookupByEmail`, caches for 1h. Sends DM via `conversations.open` + `chat.postMessage` with Block Kit message containing a "Review and decide" button. Gracefully falls back if user not found in Slack (email adapter should still deliver).

Individual channel failures do not block other channels. All notification attempts (success and failure) are recorded in the `notification_attempts` operational table for ops visibility. The dispatcher returns aggregated results to the caller for logging.

**Approval UI (Next.js).** Server-rendered, mobile-first. Routes:
- `/a/{approval_token}` — approver landing, renders layout-specific component
- `/ledger` — auditor/operator view of ledger entries (auth required)

Approval tokens are signed, single-use-per-decision (re-openable for viewing after decision), and carry the approval ID. Opening the page does not require login for the magic-link flow; submitting a decision does (weak proof-of-identity for attribution).

Layouts live in `/components/layouts/{layout_id}/`. Each exports a `Layout` React component consuming a typed payload. The `financial_decision`, `document_review`, and `procedure_signoff` ship in v1.

**Timeout Worker.** Single background worker using APScheduler. Polls for approvals with `status='pending' AND timeout_at < now()`. For each:
- If policy says `on_timeout: escalate`, mark current approval as timed-out, create new approval for escalate_to, notify.
- If policy says `on_timeout: fail`, mark timed-out, emit resume with `decision_type: timeout`, let the graph handle it.

Implementation note: we considered using Postgres `LISTEN/NOTIFY` for tighter latency but opted for 15-second poll intervals. Latency on timeout is not critical — an escalation 15 seconds late is not a problem. Keeps the architecture simpler.

**Ledger Store.** Append-only Postgres table. Primary access patterns:
- Write once on decision completion (plus lightweight update on resume ACK from SDK).
- Query by thread_id (auditor looking up a specific agent run).
- Query by approver_id (auditor reviewing one person's decisions).
- Query by date range (bulk export for compliance).
- Full-text search on rationale_notes (post-1.0 with pg_trgm).

Export formats in v1: JSON (full fidelity), CSV (flattened for spreadsheets). Post-1.0: OTLP spans, Langfuse-compatible annotations.

### 6.3 Data model

```sql
-- Simplified, actual migrations handle indices, constraints, etc.

-- Reserved for multi-tenancy (see §6.5). In v1.0, a single default row exists.
-- In v1.5+, this becomes the scoping boundary for all other tables.
CREATE TABLE applications (
    id              TEXT PRIMARY KEY,               -- Human-readable: "prod_refund_agent"
    display_name    TEXT NOT NULL,
    api_key_hash    TEXT NOT NULL,                  -- SDK authenticates with this
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE interrupts (
    id              UUID PRIMARY KEY,
    application_id  TEXT NOT NULL REFERENCES applications(id) DEFAULT 'default',
    thread_id       TEXT NOT NULL,
    trace_id        TEXT,
    layout          TEXT NOT NULL,
    payload         JSONB NOT NULL,
    policy_name     TEXT,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_interrupts_thread ON interrupts(application_id, thread_id);

CREATE TABLE approvals (
    id                  UUID PRIMARY KEY,
    interrupt_id        UUID NOT NULL REFERENCES interrupts(id),
    approver_id         TEXT,                           -- Resolved at routing time
    acting_for          TEXT,                           -- Reserved for v1.1+: non-null when this approval is a delegated substitute
    status              TEXT NOT NULL,                  -- pending, decided, timed_out, escalated
    timeout_at          TIMESTAMPTZ NOT NULL,
    escalated_to        UUID REFERENCES approvals(id),  -- Self-reference for escalation chain
    delegation_reason   TEXT,                           -- Reserved for v1.1+: "out_of_office" | "manual" | null
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_approvals_pending ON approvals(status, timeout_at) WHERE status = 'pending';

CREATE TABLE decisions (
    id                  UUID PRIMARY KEY,
    approval_id         UUID NOT NULL REFERENCES approvals(id),
    approver_email      TEXT NOT NULL,
    decision_type       TEXT NOT NULL,          -- approve, modify, escalate, reject
    decision_payload    JSONB,
    rationale_category  TEXT,
    rationale_notes     TEXT,
    decided_via         TEXT NOT NULL,          -- web_ui, api, slack_inline, email
    review_duration_ms  INT,
    signature           TEXT NOT NULL,          -- Server signature over the entry
    decided_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE ledger_entries (
    id                  UUID PRIMARY KEY,
    application_id      TEXT NOT NULL REFERENCES applications(id) DEFAULT 'default',
    interrupt_id        UUID NOT NULL REFERENCES interrupts(id),
    decision_id         UUID REFERENCES decisions(id),  -- NULL if timed_out with no decision
    resume_status       TEXT NOT NULL,
    resume_latency_ms   INT,
    content             JSONB NOT NULL,         -- Full structured entry per §5.3 — canonical record
    content_hash        TEXT NOT NULL,          -- SHA-256 of content for tamper detection
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ledger_thread ON ledger_entries(application_id, (content->>'thread_id'));
CREATE INDEX idx_ledger_created ON ledger_entries(application_id, created_at DESC);

-- Notification delivery tracking (operational, not part of canonical ledger)
CREATE TABLE notification_attempts (
    id              UUID PRIMARY KEY,
    application_id  TEXT NOT NULL REFERENCES applications(id) DEFAULT 'default',
    approval_id     UUID NOT NULL REFERENCES approvals(id),
    channel         TEXT NOT NULL,          -- email, webhook, slack
    approver_email  TEXT NOT NULL,
    success         BOOLEAN NOT NULL,
    message_id      TEXT,                   -- Channel-specific tracking ID
    error           TEXT,
    duration_ms     INT,
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_notifications_approval ON notification_attempts(application_id, approval_id);

-- Approver directory with reserved OOO fields (v1.1+)
CREATE TABLE approvers (
    id                      TEXT PRIMARY KEY,       -- "finance_lead"
    email                   TEXT NOT NULL,
    display_name            TEXT,
    ooo_active              BOOLEAN DEFAULT FALSE,  -- Reserved for v1.1+
    ooo_from                TIMESTAMPTZ,            -- Reserved for v1.1+
    ooo_until               TIMESTAMPTZ,            -- Reserved for v1.1+
    ooo_delegate_to         TEXT REFERENCES approvers(id)   -- Reserved for v1.1+
);
```

Notes:
- **Canonical vs operational.** `ledger_entries.content` (JSON per §5.3) is the canonical business record. `interrupts`, `approvals`, and `decisions` are operational projections — they exist for query performance and the running state machine. A compliance export always serializes from `ledger_entries.content`.
- **Escalation vs delegation.** `approvals.escalated_to` handles timeout-driven handoff (documented in §6.2). `approvals.acting_for` + `approvals.delegation_reason` are reserved for v1.1+ to capture OOO-driven substitution. These are distinct concepts: escalation is reactive (approver didn't respond), delegation is proactive (approver arranged coverage in advance).
- **Transactionality.** All writes are transactional: interrupt → approval creation → notification → (eventually) decision → ledger entry. Partial failure (e.g., notification fails) is recoverable because the approval record exists with `status='pending'`.
- **Notification tracking.** `notification_attempts` is an operational table — not part of the canonical ledger. It exists for ops visibility (which channels succeeded, which failed, latency) and debugging. The ledger entry records `approval.channel` (which channel the approver was notified through) but not the full delivery log. Notification failures are non-fatal: a failed Slack DM doesn't block email delivery or prevent the approval from proceeding.
- **Tenant boundary.** `application_id` is present on every table that carries business data, defaulted to `'default'` in v1.0. In v1.5+, a higher-level `organizations` concept will introduce the real tenant boundary; `applications` will become children of organizations. All current indexes already lead with `application_id` for this reason.

### 6.4 Flow: interrupt to resume

1. Agent calls `@approval_gate`-wrapped node. Decorator intercepts `interrupt()` call.
2. SDK POSTs payload to `/interrupts`. Server creates `interrupts` row, evaluates policy, creates `approvals` row with `status='pending'` and `timeout_at = now + policy.timeout`.
3. Server fires notifications synchronously (policy evaluation is fast; notification is I/O-bound but parallel). Response to SDK: `{approval_id, status: 'pending'}`.
4. SDK enters a long-poll loop (or WebSocket subscription; poll in v1 for simplicity) on `/approvals/{approval_id}/status`.
5. Meanwhile, approver clicks the notification link, hits `/a/{token}`. Server renders the layout with the payload. Approver makes decision, submits to `/approvals/{id}/decide`.
6. Server validates signature + approver identity, writes `decisions` row, composes `ledger_entries` row, sets `approvals.status='decided'`.
7. SDK poll sees state change, returns `decision_payload` to its caller. Decorator returns, LangGraph flow continues. SDK POSTs resume ACK to close the ledger entry with `resume_status`.

Alternative paths (timeout, escalation, manual override via API) follow the same skeleton.

### 6.5 Key design decisions

This section records decisions that are firmly chosen for v1 and the reasoning behind each. Some of these close what were previously open questions; they're recorded here so future contributors understand the intent, not just the implementation.

#### Technical decisions

**SDK long-poll over WebSocket.** Simpler, works through all networks, adequate latency for this use case. WebSocket is a v1.1 option if adoption demands it.

**Postgres-only for v1.** No Redis, no ClickHouse. Single database simplifies ops and recovery. Postgres handles our scale (thousands of decisions per day per instance) fine. If a deployment needs more, they can scale Postgres; if much more, they're probably a managed-cloud customer.

**Server-rendered approval UI.** SPA-style would require API auth roundtrips for each approver view. SSR lets us render from the signed token server-side and ship minimal JS. Critical for email-link flow where the approver hasn't logged in.

**No LangGraph version coupling in the server.** The server knows nothing about LangGraph's internals — it just has a request/response API. The SDK is where LangGraph-specific integration lives. If LangGraph changes its internals significantly, only the SDK updates.

**Opinionated policy expression language.** We will be asked to support Rego, CEL, or JavaScript expressions. Resist. The simple language covers the 95% case and its limitations are features: it forces users to pre-process complexity in their agent, which is the right place for it.

#### Product decisions

These five decisions resolve what were previously open product questions. Each has a clear rationale and a deferred extension path.

**Slack UX: web-UI-only for v1, Slack inline as v1.2 opt-in.** Slack messages for Deliberate carry context and a "Review" button — all decisions happen in the web UI. Slack's block-UI constraints can't cleanly express the full set of decision types and structured rationale that make our ledger valuable. Forcing approvers through the web for v1 establishes the habit of complete decision capture. In v1.2, `slack_inline: approve_reject_only` will become an opt-in per-policy flag for simple cases; the web UI path remains default for anything involving `modify` or required rationale.

**Delegation: schema-reserved in v1, out-of-office activation in v1.1, full framework post-v2.** No delegation logic ships in v1.0. But `policy.approvers.backup_delegate`, `approvers.ooo_*` columns, and `ledger.approval.acting_for` are all in the schema from day one. When v1.1 activates OOO-style delegation (single-level, time-bounded, approver-configured), no migration runs and no policy file rewrite is needed. More sophisticated patterns — conditional delegation, delegation chains, role-based — are deferred to v2.0+ when a proper auth/RBAC feature is introduced. This sequencing matches how organizations actually adopt approval tooling: simple coverage first, structured delegation later.

**Ledger as source of truth.** The canonical business record is `ledger_entries.content` (the full JSON object defined in §5.3). The normalized `interrupts`, `approvals`, and `decisions` tables exist for operational queries and the running state machine, but a compliance export always serializes from the ledger content, and the content hash + signature attest to *the ledger* — not to the operational tables. The alternative design (ledger as a projection of normalized tables, rebuildable on demand) was rejected because it weakens the audit claim: the ledger would need to be recomputed to prove a past state, and the tables themselves would technically be the record. For a product whose core value is decision auditability, the ledger must be unambiguously the record. The tradeoff — we must get every ledger write correct on the first try — is accepted and addressed through write transactionality and tests.

**Tenant model: single-tenant in v1, `application_id` schema-reserved for v1.5+ organizations.** v1.0 ships single-tenant — one Deliberate instance serves one organization. But every data-carrying table has an `application_id` column (defaulted to `'default'`), and all indexes lead with it. Users can register multiple `applications` (one per agent or environment) in v1.0 with shared policies and approvers. When managed cloud ships in v1.5+, an `organizations` concept will enclose applications and introduce the real tenant boundary; the column layout is already ready. Multi-tenancy in open source without auth primitives would be a security footgun (wrong tenant_id on one query = data leak); the path is to ship single-tenant first, then layer the isolation story with managed-cloud's stronger ops controls.

**LangGraph version support: latest three minor versions.** The SDK targets LangGraph's most recent three minor releases, running CI against each. When LangGraph ships a new minor, the oldest supported version ages out within one Deliberate minor release cycle (with at least 30 days' notice in release notes). Where possible, the SDK uses LangGraph's public API; where internal APIs are needed (e.g., for interrupt interception), the SDK documents which internals it depends on and tests against version bumps early. Users can pin Deliberate and LangGraph independently as long as they stay within a supported combination — see Appendix B for the compatibility matrix.

### 6.6 Security model

**Approval tokens.** Short-lived (default 7 days, policy-configurable), signed with HS256 using a server secret. Contain the approval ID and nothing sensitive. Re-openable after decision for record viewing, but decision endpoint rejects submissions after decision completes.

**Approver identity.** On first visit with a magic-link token, Deliberate sets a session cookie bound to the approver's email (as specified in policy). Submitting a decision requires the cookie. For higher assurance, OAuth flow (Google/GitHub) is supported in v1 — users configure which flow applies per approver or group.

**Agent-server authentication.** The SDK authenticates with a long-lived API key (generated in Deliberate's admin UI). Each interrupt is scoped to an "application" (one per agent/environment typically). Keys are hashable, rotatable.

**Webhook signing.** Outbound webhooks include an `X-Deliberate-Signature` header — HMAC-SHA256 over the body with a per-webhook secret. Consumers verify to reject forged calls.

**Ledger integrity.** The ledger is the source of truth (§6.5), so its integrity is the integrity of the product's core claim. Every ledger entry includes a SHA-256 hash of its content fields plus a server signature over that hash. If the operational tables and the ledger ever disagree, the ledger wins. Post-1.0 we plan to add chained hashes (each entry references the hash of the previous) for tamper-evident append-only semantics, but this requires ops discipline to maintain correctly across migrations — deferred to avoid premature complexity.

**Data handling.** Deliberate stores interrupt payloads verbatim. Sensitive data stays in user infrastructure — we don't proxy large artifacts (>1MB), we don't transform payloads beyond layout rendering, and self-hosting means data never leaves the user's boundary. For managed cloud (post-1.0), this becomes a substantial additional consideration.

### 6.7 Deployment

Primary deployment is Docker Compose with four services:

```yaml
services:
  postgres:
    image: postgres:16
    volumes: [pgdata:/var/lib/postgresql/data]

  server:
    image: deliberate/server:latest
    depends_on: [postgres]
    environment:
      DATABASE_URL: postgres://...
      SECRET_KEY: ${SECRET_KEY}
      SLACK_BOT_TOKEN: ${SLACK_BOT_TOKEN}
      SMTP_HOST: ...
    ports: ["4000:4000"]

  worker:
    image: deliberate/server:latest
    command: ["deliberate-worker"]
    depends_on: [postgres]
    environment: { ... }

  ui:
    image: deliberate/ui:latest
    environment:
      NEXT_PUBLIC_API_URL: http://server:4000
    ports: ["3000:3000"]

volumes:
  pgdata:
```

A single `docker compose up` gets all four running. First-run bootstrap creates the database schema via Alembic migrations. The quickstart doc walks through configuring one notification channel (Slack recommended for fastest visual gratification) and registering an application to get an SDK API key.

For production, users typically:
- Run Postgres externally (managed RDS, Cloud SQL, etc.)
- Run server + worker + UI on any container host (Fly.io, Railway, ECS, GKE)
- Point SMTP at an existing provider (SendGrid, SES, Postmark)

Kubernetes Helm chart is planned for v1.1.

---

## 7. Milestones

### M1 — Internal prototype (end of week 2)

- SDK decorator working end-to-end against a locally running server
- Server handles one interrupt, renders one layout (financial_decision) in browser, captures decision, resumes agent
- Postgres schema in place, basic ledger writing
- No notifications yet — approver URL manually copied from logs
- No policy yet — single configured approver in environment variable
- Docker Compose setup functional but rough

### M2 — First-use ready (end of week 4)

M2 is split into sub-milestones:

**M2a — Policy engine + Notification adapters:**
- 🚧 YAML policy engine with expression evaluator per §5.2 (auto-approve, any_of, all_of)
- 🚧 Approver directory (`approvers.yaml`) with hot-reload
- 🚧 SMTP email notification adapter with HTML templates
- 🚧 Webhook notification adapter with HMAC-SHA256 signing
- 🚧 Slack DM notification adapter (private app install, no inline approval)
- 🚧 Notification dispatcher with parallel delivery and `notification_attempts` table

**M2b — Timeout worker + Additional layouts:**
- Timeout worker implementing timeout and single-level escalation
- Two additional layouts (document_review, procedure_signoff)

**M2c — Quickstart + Release:**
- Quickstart documentation with 15-minute install-to-first-approval target
- Release as `v0.1.0` on PyPI and Docker Hub. Announce on LangGraph Discord, relevant Reddit subs, and Hacker News (Show HN).

### M3 — Ledger and audit (end of week 8)

- Ledger entry signing and content-hash verification
- Ledger query UI for auditors, unified with the approval layout (audit mode renders the same layout as decision mode, with decision record in place of decision form)
- JSON and CSV export
- Webhook notification adapter with signed payloads
- Approver identity via Google OAuth (GitHub post-1.0)
- Full CONTRIBUTING.md with good-first-issues labeled

Release as `v0.2.0`. At this point the project is genuinely useful for small teams putting LangGraph agents into production.

### M4 — v1.0 (end of week 16)

- Three more layouts (data_access, content_moderation, code_deployment)
- Custom layout SDK (document the path for teams to build their own layouts)
- Production-readiness pass: observability (Prometheus metrics, structured logs), graceful shutdown, migration safety
- OTLP export for ledger (feeds into Langfuse, Phoenix, etc.)
- Security review and threat model documented
- v1.0 release with stability commitments on the three schemas (§5)

---

## 8. Risks and open questions

### 8.1 Risks

**LangGraph moves to close the gap.** If LangChain team ships an official approver-facing UI layer, Deliberate's core value dissolves. Mitigation: depth and opinionation. Our built-in layouts and approver-UX focus are the defensible investment; a framework vendor is unlikely to ship six domain-specific layouts with the same care. Also, being open source from day one and LangGraph-native means LangChain itself could adopt or integrate with us.

**Adoption depends on people already using LangGraph at non-trivial scale.** The population of "LangGraph users who need approval beyond same-session interactions" is real but bounded. We accept this. The alternative (supporting all frameworks) trades real depth for shallow breadth.

**Approver UX is subjective.** Good UX doesn't test well in isolation. Mitigation: ship usable v1 quickly, iterate based on real user feedback, publish opinionated design decisions (like the 30-second rule, rationale chips over free text) so users understand the thinking and can push back specifically.

**Policy YAML is brittle for complex cases.** Users will want more expression power. Resist for v1, but document the extension path clearly (pre-process the payload in the agent, or use `decision_options` to narrow the approver's choices).

**Self-host security burden on users.** Users will misconfigure SMTP, expose admin endpoints, use weak secrets. Mitigation: sensible defaults, setup-time validation, prominent security documentation. Post-1.0 managed cloud is the real answer for users who don't want this burden.

**Getting the ledger schema wrong.** Because the ledger is the source of truth (§6.5), mistakes in the schema design propagate into the permanent record. Mitigation: stability commitment on schema fields only at v1.0 (not before), aggressive stress-testing against real use cases during M1–M3, and reserving extension fields (e.g., `acting_for`) well before they're needed.

### 8.2 Resolved design decisions

The following were open questions in earlier PRD drafts. They are now resolved and documented in §6.5. Summarized here for quick reference:

| Question | Resolution | Reference |
|---|---|---|
| Slack inline approval vs web UI | Web UI only for v1; Slack inline as opt-in in v1.2 | §6.5 |
| Delegation of approvals | Schema-reserved in v1.0; OOO-style activation in v1.1; fuller framework post-v2.0 with auth | §5.2, §5.3, §6.3, §6.5 |
| Ledger as source of truth or view | Source of truth | §5.3, §6.5, §6.6 |
| Multi-tenant in open source | Single-tenant for v1.0; `application_id` schema-reserved for v1.5+ | §6.3, §6.5 |
| LangGraph version support | Latest three minor versions, with compatibility matrix | §6.5, Appendix B |

### 8.3 Still open

**Should the API gateway include a small admin UI for rotating SDK keys and registering applications, or is CLI-only sufficient for v1?** Leaning CLI for v1 to keep surface area small. Most operators are comfortable with CLI, and admin-UI surface is a security risk if left with default credentials. Reconsider if M2 user feedback says otherwise.

**How do we handle payload size gracefully when approvers are on mobile with limited bandwidth?** We cap interrupt payloads at 1MB (§4.3), but even 500KB is heavy on slow connections. Options: progressively load evidence sections, transcode images server-side, or hard-cap evidence items to ~10 per interrupt. Probably a mix; needs empirical testing with the demo deployment.

**Do we include a reference LangGraph agent in the repo, or keep integration examples in a separate `examples/` repo?** Current plan: one reference agent in `examples/refund_agent` within the main repo (for the quickstart), detailed examples in a separate repo. Revisit if the examples folder grows large enough to confuse people about what's part of the library itself.

**Timeline for a managed cloud offering.** Not v1. Probably v1.5+. Open question is whether we commit to a date now (risky — managed cloud has substantial additional work) or stay vague until open-source adoption signals demand (probably correct).

---

## 9. What v1.0 is not (and that's fine)

v1.0 is deliberately small. It does one thing — route agent-interrupt-to-human-approval with good UX and clean audit — for one framework, with three channels and three layouts.

It is not:
- A full agent observability platform (use Langfuse, Phoenix)
- A workflow orchestrator (use Temporal, Prefect)
- An authorization system (use Permit.io, OpenFGA)
- An enterprise BPMN engine (use Camunda)

Holding the scope tight is how we get the approver UX right and ship something actually used, instead of something broad and mediocre. Growth comes from depth first — additional layouts, deeper LangGraph integration, better audit primitives — and only later from breadth.

---

## Appendix A — Competitive positioning reference

| | LangGraph native | Permit.io | Handover | Langfuse | **Deliberate** |
|---|---|---|---|---|---|
| Primary concern | Agent runtime | Authorization | Out-of-band approval | Observability | Approver UX + audit |
| Pause/resume primitive | ✅ native | ○ via MCP | ✅ | — | uses LangGraph's |
| Notifications | ❌ | ○ | ✅ email | — | ✅ Slack/Email/Webhook |
| Timeout + escalation | ❌ | ○ policy-level | ✅ | — | ✅ |
| Structured audit log | ❌ | ○ access log | ✅ | ◐ annotations | ✅ first-class |
| Built-in approver UI | ❌ | △ admin | △ generic | — | ✅ domain-tuned |
| Open source | ✅ | partial | ❌ | ✅ | ✅ |
| LangGraph-native | self | ❌ | ◐ adapter | ◐ callback | ✅ |

(Reference only — not for external marketing. Public framing uses "Related projects" positioning that acknowledges each tool's primary concern.)

## Appendix B — LangGraph version compatibility

Deliberate SDK supports the three most recent LangGraph minor releases. When a new minor releases, the oldest supported minor is deprecated with at least 30 days' notice in release notes, and removed in the following Deliberate minor.

| Deliberate SDK | LangGraph 0.2.x | LangGraph 0.3.x | LangGraph 0.4.x | LangGraph 0.5.x |
|---|:---:|:---:|:---:|:---:|
| 0.1.x | ✅ | ✅ | ✅ | — |
| 0.2.x | ✅ | ✅ | ✅ | — |
| 1.0.x (planned) | ⚠️ deprecated | ✅ | ✅ | ✅ |

Legend: ✅ supported · ⚠️ deprecated (works, will drop next minor) · ❌ incompatible · — not released yet

The SDK uses LangGraph's public API where possible. Internals we currently depend on (to be documented in `SDK_INTERNALS.md`):

- `interrupt()` — graph-pausing primitive (public, stable)
- `Command(resume=...)` — resume signal (public, stable)
- Access to the checkpointer via graph config (public, stable)
- Thread ID resolution from node context (semi-public; tracked for changes)

When LangGraph changes any of these in a breaking way, Deliberate pins to the last working LangGraph version and ships a compatibility patch within two weeks.

## Appendix C — Glossary

- **Application.** A registered agent or environment in Deliberate (e.g., "prod_refund_agent", "staging_legal_review"). Interrupts are scoped to an application. Schema-reserved as the v1.5+ tenant child.
- **Approval gate.** A LangGraph node wrapped with `@approval_gate`; every invocation produces an interrupt routed through Deliberate.
- **Approver.** The human (or human group) who decides on an interrupted agent's proposed action.
- **Backup delegate.** An approver designated in policy to receive routing when the primary approver is out-of-office. Schema-reserved in v1.0, activated in v1.1.
- **Decision.** The structured record of an approver's response, including type (approve/modify/escalate/reject), payload, and rationale.
- **Delegation.** Proactive, approver-arranged substitution (e.g., OOO coverage). Distinct from escalation. Activates in v1.1.
- **Escalation.** Reactive, timeout-driven reassignment of a pending approval to a backup approver when the original doesn't respond. Ships in v1.0.
- **Interrupt.** The LangGraph primitive that pauses graph execution, as captured and enriched by Deliberate's SDK.
- **Layout.** An opinionated information architecture for the approver UI, tuned to a specific decision domain (financial, document, procedure, etc.).
- **Ledger.** The append-only, structured record of every decision, designed for audit and compliance export. The canonical business record.
- **Policy.** A declarative YAML document mapping interrupt characteristics to approvers, timeouts, and escalation rules.
