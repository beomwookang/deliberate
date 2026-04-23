# Deliberate Quickstart

Deliberate is a human-approval layer for LangGraph agents. When your agent needs to pause and ask for approval before taking high-stakes action, Deliberate routes the request to the right person, sends notifications, and captures an audit trail of who decided what and why.

This guide will get you up and running in 15 minutes.

## Prerequisites

- **Docker & Docker Compose** — for running Postgres, the server, worker, and UI
- **Python 3.11+** and `uv` — for running the example agent
- **Node.js 18+** and `pnpm` — for building the UI (optional; Docker Compose handles this)
- **Slack Bot Token** (optional) — for Slack notifications

If you don't have these installed, see the [full installation guide](./INSTALLATION.md).

## Quick Start (15 minutes)

### 1. Clone the repository

```bash
git clone https://github.com/your-handle/deliberate.git
cd deliberate
```

### 2. Set up environment variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` and fill in `SECRET_KEY`:

```bash
# Generate a random secret key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the output into the `SECRET_KEY` field in `.env`. Leave other fields as defaults for now.

```env
SECRET_KEY=your-generated-key-here
DATABASE_URL=postgresql+asyncpg://deliberate:deliberate@localhost:5432/deliberate
DEFAULT_APPROVER_EMAIL=approver@example.com
UI_URL=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:4000
INTERNAL_API_URL=http://server:4000
DELIBERATE_SERVER_URL=http://localhost:4000
DELIBERATE_API_KEY=SmZ-5ETlbm4v-sGgwSd33SE2VMbBbxxdQt0dvR2U8hs
DELIBERATE_UI_URL=http://localhost:3000
```

### 3. Start the full stack

```bash
docker compose up -d
```

This starts:
- **Postgres** (database) on port 5432
- **Server** (FastAPI) on port 4000
- **Worker** (background tasks) — no exposed port
- **UI** (Next.js) on port 3000

Verify services are running:

```bash
docker compose ps
```

Wait 10-15 seconds for the database migrations to complete, then verify the server health:

```bash
curl http://localhost:4000/health
```

You should see:

```json
{"status": "healthy"}
```

### 4. Set up approvers and policies

By default, the config files are in `./config/`:

- **Approvers**: `./config/approvers.yaml` — who can approve what
- **Policies**: `./examples/policies/refund.yaml` — rules for routing approvals

These are already pre-populated. You can view them:

```bash
cat config/approvers.yaml
cat examples/policies/refund.yaml
```

For now, leave them as-is. See **Configuration Reference** below if you want to customize.

### 5. Run the example agent

The example is a CS response review agent that uses `@approval_gate` to pause and ask for human approval.

Open a new terminal and run:

```bash
cd examples/refund_agent
uv pip install -e ".[dev]"
uv run python dogfood.py
```

You'll see output like:

```
==================================================
Dogfooding — CS 응답 검토 에이전트
==================================================

고객: 김민지
문의: 예약한 숙소 체크인 시간을 변경할 수 있나요?
Thread: 123e4567-e89b-12d3-a456-426614174000

[AI] 응답 초안 생성 완료 (186자)
[Waiting for approval...]
Approval URL: http://localhost:3000/a/550e8400-e29b-41d4-a716-446655440000
```

### 6. Open the approval page

Copy the approval URL from the logs and open it in your browser:

```
http://localhost:3000/a/550e8400-e29b-41d4-a716-446655440000
```

You'll see the approval page with:
- The draft response
- Customer information
- Decision buttons (Approve, Reject, Modify, Escalate)
- Rationale category (why you're approving/rejecting)
- Notes field (optional comments)

### 7. Submit a decision

Click **Approve** (or Reject/Modify if you prefer). The agent in your terminal will immediately resume, log the decision, and complete.

You should see:

```
==================================================
응답 전송 완료!
  고객: 김민지
  응답: 안녕하세요 김민지님, ...
  판정: approve
  사유: N/A
==================================================

에이전트 완료.
최종 판정: approve
```

Congratulations! You've completed a full approval flow.

## Configuration Reference

### Environment Variables

#### Required

- **`SECRET_KEY`** — Server signing secret. Used to create HMAC signatures for approval decisions. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. No default.

#### Database

- **`DATABASE_URL`** — PostgreSQL async connection string.
  - Default: `postgresql+asyncpg://deliberate:deliberate@localhost:5432/deliberate`

#### Server

- **`SERVER_HOST`** — Server bind address. Default: `0.0.0.0`
- **`SERVER_PORT`** — Server port. Default: `4000`

#### UI URLs

- **`UI_URL`** — Public URL of the approval UI (used in notification links).
  - Default: `http://localhost:3000`
- **`NEXT_PUBLIC_API_URL`** — Public API URL visible to the browser.
  - Default: `http://localhost:4000`
- **`INTERNAL_API_URL`** — Internal API URL (used by the UI server). Default: `http://server:4000`

#### SDK (Agent)

- **`DELIBERATE_SERVER_URL`** — Server URL for the agent SDK.
  - Default: `http://localhost:4000`
- **`DELIBERATE_API_KEY`** — API key for the agent. No default; agents will fail if not set.
- **`DELIBERATE_UI_URL`** — URL where approval pages are accessible.
  - Default: `http://localhost:3000`

#### Policies & Approvers

- **`POLICIES_DIR`** — Directory containing policy YAML files.
  - Default: `/etc/deliberate/policies`
  - Docker Compose: `./examples/policies`
- **`APPROVERS_FILE`** — Path to approvers YAML.
  - Default: `/etc/deliberate/approvers.yaml`
  - Docker Compose: `./config/approvers.yaml`
- **`WEBHOOKS_FILE`** — Path to webhooks YAML (for webhook notifications).
  - Default: `/etc/deliberate/webhooks.yaml`
  - Docker Compose: `./config/webhooks.yaml`

#### Notifications — Slack

- **`SLACK_BOT_TOKEN`** — Slack Bot token for notifications. Optional. If not set, Slack notifications are skipped.
- **`SLACK_SIGNING_SECRET`** — Slack signing secret. Optional.

#### Notifications — Email (SMTP)

- **`SMTP_HOST`** — SMTP server address. Optional. If not set, email notifications are skipped.
- **`SMTP_PORT`** — SMTP port. Default: `587`
- **`SMTP_USERNAME`** — SMTP username. Optional.
- **`SMTP_PASSWORD`** — SMTP password. Optional.
- **`SMTP_FROM_EMAIL`** — From address for emails. Default: `noreply@example.com`
- **`SMTP_FROM_NAME`** — From name for emails. Default: `Deliberate`
- **`SMTP_USE_TLS`** — Use TLS for SMTP. Default: `true`

#### M1 Fallback (Deprecated)

- **`DEFAULT_APPROVER_EMAIL`** — Single approver email for M1 (no policy engine). Deprecated; use policies instead. No default; if no policy matches and this is not set, the server returns 400.

### Policy YAML Format

Policies define which approvers handle which requests. Stored in `POLICIES_DIR` (or `./examples/policies` in Docker Compose).

Example: `refund.yaml`

```yaml
name: refund_approval
matches:
  layout: financial_decision
  subject_contains: "Refund"

rules:
  # Auto-approve small refunds
  - name: auto_approve_small
    when: "amount.value < 100"
    action: auto_approve
    rationale: "Below $100 threshold"

  # Standard amount: any finance team member
  - name: standard
    when: "amount.value >= 100 and amount.value < 5000"
    approvers:
      any_of: [finance_team]
    timeout: 4h
    on_timeout: escalate
    escalate_to: finance_lead
    notify: [email, slack]

  # High value: two-person approval
  - name: high_value
    when: "amount.value >= 5000"
    approvers:
      all_of: [finance_lead, cfo]
    timeout: 8h
    on_timeout: fail
    require_rationale: true
    notify: [email, slack, webhook]
```

#### Policy structure

- **`name`** — Policy identifier
- **`matches`** — Conditions to apply this policy:
  - **`layout`** — Layout type (e.g., `financial_decision`)
  - **`subject_contains`** — String to match in the `subject` field
- **`rules`** — Array of approval rules (evaluated top-to-bottom, first match wins):
  - **`name`** — Rule identifier
  - **`when`** — Expression to trigger this rule (see Expression Language below)
  - **`action`** — `auto_approve` or (omitted: request human approval)
  - **`approvers`** — Who to send the approval to:
    - **`any_of`** — List of approver IDs; first to approve wins
    - **`all_of`** — List of approver IDs; all must approve
  - **`timeout`** — Time before escalation (e.g., `4h`, `2d`). Optional.
  - **`on_timeout`** — `escalate` or `fail`. Optional.
  - **`escalate_to`** — Approver ID to escalate to if timeout. Optional.
  - **`notify`** — Notification channels: `email`, `slack`, `webhook`. Optional.
  - **`require_rationale`** — If true, approver must provide notes. Default: false.

### Expression Language

Expressions in the `when` field support:

- **Operators**: `<`, `>`, `<=`, `>=`, `==`, `!=`, `and`, `or`, `not`
- **Operators (text)**: `contains`
- **Field access**: `payload.field_name` (e.g., `amount.value`, `customer.email`)
- **Missing fields**: Evaluate to `false` (not an error)

Examples:

```yaml
# Numeric comparison
when: "amount.value >= 5000"

# Boolean AND
when: "amount.value >= 100 and amount.value < 5000"

# Negation
when: "not (customer.is_vip)"

# Text search
when: "subject contains 'refund'"

# Complex expression
when: "amount.value > 1000 and (customer.is_vip or agent_reasoning contains 'fraud')"
```

### Approvers YAML Format

File: `./config/approvers.yaml`

Maps approver IDs (used in policies) to real people and groups.

```yaml
approvers:
  - id: finance_lead
    email: priya@acme.com
    display_name: "Priya Sharma"
    out_of_office:
      active: false
      from: null
      until: null
      delegate_to: null

  - id: cfo
    email: cfo@acme.com
    display_name: "Alex Chen"

groups:
  - id: finance_team
    members: [finance_lead, cfo]
```

#### Approver fields

- **`id`** — Unique identifier (used in policies)
- **`email`** — Email address (used for notifications and UI)
- **`display_name`** — Human-friendly name
- **`out_of_office`** — Schema-reserved (not yet used in M2a; placeholder for v1.1)

#### Group fields

- **`id`** — Group identifier
- **`members`** — List of approver IDs in the group

### Webhooks YAML Format

File: `./config/webhooks.yaml`

For webhook notifications, list the endpoints to call when approvals are created:

```yaml
webhooks:
  - id: internal_audit
    url: https://audit.example.com/webhook/approval
    secret: webhook-secret-key-here
    active: true

  - id: slack_audit
    url: https://hooks.slack.com/services/YOUR/WEBHOOK/URL
    secret: ""
    active: false
```

#### Webhook fields

- **`id`** — Unique identifier
- **`url`** — Endpoint URL
- **`secret`** — HMAC secret (optional; used to sign payloads)
- **`active`** — Enable/disable this webhook

Payloads are signed with `X-Deliberate-Signature` header (HMAC-SHA256).

## API Reference

All API calls to the server require the `X-Deliberate-API-Key` header (except UI endpoints).

### Health Check

```
GET /health
```

Returns:

```json
{"status": "healthy"}
```

### Submit Interrupt

```
POST /interrupts
Header: X-Deliberate-API-Key: <api-key>
```

Request body:

```json
{
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "trace_id": "optional-trace-id",
  "payload": {
    "subject": "Refund for customer #4821",
    "layout": "financial_decision",
    "amount": { "value": 750.00, "currency": "USD" },
    "customer": { "id": "4821", "display_name": "Alice Johnson" },
    "agent_reasoning": "Customer reported shipping damage; invoice shows $750 refund justified.",
    "evidence": [
      {
        "type": "invoice",
        "id": "INV-2024-001",
        "summary": "Original order: $750",
        "url": "https://example.com/invoices/INV-2024-001"
      }
    ],
    "rationale_categories": ["damage", "customer_service", "other"]
  }
}
```

Response:

```json
{
  "approval_group_id": "550e8400-e29b-41d4-a716-446655440000",
  "approval_ids": ["550e8400-e29b-41d4-a716-446655440001"],
  "approval_mode": "any_of",
  "status": "pending",
  "decision_type": null,
  "approval_id": "550e8400-e29b-41d4-a716-446655440001"
}
```

For `all_of` approvals, `approval_ids` will have multiple entries.

### Get Approval Status

```
GET /approvals/{approval_id}/status
```

Returns:

```json
{
  "status": "pending",
  "approval_id": "550e8400-e29b-41d4-a716-446655440001",
  "decision_type": null,
  "decision_payload": null,
  "rationale_category": null,
  "rationale_notes": null
}
```

After decision:

```json
{
  "status": "decided",
  "approval_id": "550e8400-e29b-41d4-a716-446655440001",
  "decision_type": "approve",
  "decision_payload": null,
  "rationale_category": "damage",
  "rationale_notes": "Confirmed shipping damage. Refund approved."
}
```

### Get Approval Payload (for UI)

```
GET /approvals/{approval_id}/payload
```

Returns the original interrupt payload (for rendering the approval page):

```json
{
  "approval_id": "550e8400-e29b-41d4-a716-446655440001",
  "status": "pending",
  "layout": "financial_decision",
  "payload": {
    "subject": "Refund for customer #4821",
    "amount": { "value": 750.00, "currency": "USD" },
    ...
  }
}
```

### Submit Decision

```
POST /approvals/{approval_id}/decide
```

Request body:

```json
{
  "decision_type": "approve",
  "decision_payload": null,
  "rationale_category": "damage",
  "rationale_notes": "Confirmed shipping damage. Refund approved.",
  "approver_email": "priya@acme.com",
  "review_duration_ms": 125,
  "decided_via": "web_ui"
}
```

Response:

```json
{
  "status": "decided"
}
```

Decision types: `approve`, `reject`, `modify`, `escalate`.

### Resume Acknowledgment

```
POST /approvals/{approval_id}/resume-ack
```

Called by the agent after receiving the decision and resuming, to record latency:

```json
{
  "resume_status": "resumed",
  "resume_latency_ms": 42
}
```

Response:

```json
{
  "ok": true
}
```

### Get Approval Group Status (for `all_of`)

```
GET /approval-groups/{group_id}/status
```

For `all_of` approvals, returns aggregated status:

```json
{
  "group_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "approval_ids": [
    "550e8400-e29b-41d4-a716-446655440001",
    "550e8400-e29b-41d4-a716-446655440002"
  ],
  "approvals": [
    {
      "approval_id": "550e8400-e29b-41d4-a716-446655440001",
      "approver_email": "priya@acme.com",
      "status": "pending"
    },
    {
      "approval_id": "550e8400-e29b-41d4-a716-446655440002",
      "approver_email": "cfo@acme.com",
      "status": "decided",
      "decision_type": "approve"
    }
  ]
}
```

### Query Ledger

```
GET /ledger?thread_id=<thread_id>
```

Returns all ledger entries for a thread (audit trail):

```json
{
  "entries": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "thread_id": "550e8400-e29b-41d4-a716-446655440001",
      "event_type": "interrupt_created",
      "payload": { ... },
      "created_at": "2024-04-22T10:15:30Z"
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440010",
      "thread_id": "550e8400-e29b-41d4-a716-446655440001",
      "event_type": "decision_recorded",
      "payload": {
        "approval_id": "550e8400-e29b-41d4-a716-446655440001",
        "decision_type": "approve",
        "approver_email": "priya@acme.com",
        "rationale_category": "damage"
      },
      "created_at": "2024-04-22T10:17:15Z"
    }
  ]
}
```

## SDK Usage

### Installation

Install the SDK in your agent environment:

```bash
pip install deliberate
```

Or for development (from source):

```bash
cd sdk
uv pip install -e ".[dev]"
```

### Using @approval_gate decorator

The decorator wraps a LangGraph node function and handles interrupt submission, polling, and decision return.

```python
from deliberate import approval_gate

@approval_gate(layout="financial_decision")
def process_refund(state):
    """Called when the graph reaches this node.
    
    Returns a dict with interrupt payload fields.
    The decorator submits to the server, waits for approval, and returns the decision.
    """
    return {
        "subject": f"Refund for customer #{state['customer_id']}",
        "amount": {
            "value": state['refund_amount'],
            "currency": "USD"
        },
        "customer": {
            "id": state['customer_id'],
            "display_name": state['customer_name']
        },
        "agent_reasoning": "Customer reported damage; invoice shows order was $750.",
        "evidence": [
            {
                "type": "invoice",
                "id": state['order_id'],
                "summary": "Original order",
                "url": f"https://example.com/orders/{state['order_id']}"
            }
        ],
        "rationale_categories": ["damage", "quality_issue", "other"]
    }
```

In your LangGraph definition:

```python
from langgraph.graph import StateGraph

graph = StateGraph(YourState)
graph.add_node("process_refund", process_refund)
graph.add_edge("some_node", "process_refund")
graph.add_edge("process_refund", "next_node")
```

When the graph runs and reaches `process_refund`:

1. The decorator submits the payload to Deliberate
2. Deliberate evaluates policies and creates approval(s)
3. The decorator polls for a decision (2-second intervals, 1-hour timeout by default)
4. When decided, the decorator returns `{"decision": {...}}` to the state
5. Your next node receives the decision in the state

#### Decorator parameters

```python
@approval_gate(
    layout="financial_decision",                    # Required: layout type
    notify=["email", "slack"],                      # Optional: channels
    policy="path/to/policy.yaml",                   # Optional: policy file
    timeout_seconds=3600,                           # Optional: polling timeout
    server_url="http://localhost:4000",             # Optional: server URL
    api_key="...",                                  # Optional: API key
    ui_url="http://localhost:3000"                  # Optional: UI URL
)
def your_node(state):
    ...
```

- **`layout`** (required) — Layout type for the UI
- **`notify`** — Notification channels. Not used in M2a (planned for M2b)
- **`policy`** — Policy file path. Not used in M2a (server evaluates policies)
- **`timeout_seconds`** — Polling timeout (default: 3600 seconds / 1 hour)
- **`server_url`**, **`api_key`**, **`ui_url`** — Override env vars

### Using DeliberateClient directly

For custom flows, you can use the client directly:

```python
from deliberate import DeliberateClient
from deliberate.types import InterruptPayload

client = DeliberateClient(
    base_url="http://localhost:4000",
    api_key="your-api-key",
    ui_url="http://localhost:3000"
)

# Submit an interrupt
result = await client.submit_interrupt(
    thread_id="550e8400-e29b-41d4-a716-446655440000",
    payload=InterruptPayload(
        subject="Refund request",
        layout="financial_decision",
        amount={"value": 750.00, "currency": "USD"},
        ...
    )
)

# Poll for decision
decision = await client.wait_for_decision(
    result.approval_id,
    timeout=3600
)

# Or for all_of groups:
decision = await client.wait_for_decision(
    result.approval_group_id,
    use_group=True,
    timeout=3600
)

if decision['decision_type'] == 'approve':
    # Resume the agent with the decision
    pass
```

See `deliberate.types` for all payload schemas.

## Layouts

Deliberate comes with built-in layouts for common approval scenarios. Choose the layout that matches your use case:

### financial_decision

For refunds, expense approvals, budget requests. Leads with amount and evidence.

Use when:
- Approving or rejecting a monetary transaction
- Customer refunds, vendor payments, employee reimbursements
- The primary decision factor is the amount and supporting evidence

Example:

```python
@approval_gate(layout="financial_decision")
def process_refund(state):
    return {
        "subject": "Refund for order #123",
        "amount": {"value": 500.00, "currency": "USD"},
        "customer": {"id": "C123", "display_name": "Alice"},
        "agent_reasoning": "Damage reported by customer.",
        "evidence": [...]
    }
```

### document_review

For contracts, policies, legal redlines. Leads with the document and flagged clauses.

Use when:
- Approving a document before sending
- Reviewing contracts, policies, terms of service
- The primary decision factor is document content and specific clauses

Example:

```python
@approval_gate(layout="document_review")
def review_contract(state):
    return {
        "subject": "NDA with Acme Corp",
        "document": {
            "title": "Non-Disclosure Agreement",
            "content": "...",
            "url": "https://example.com/documents/nda"
        },
        "flagged_items": [
            {
                "type": "clause",
                "summary": "5-year confidentiality period",
                "recommendation": "standard"
            }
        ]
    }
```

### procedure_signoff

For audit steps, compliance checks, quality gates. Leads with checklist and exceptions.

Use when:
- Signing off on a procedural step
- Compliance audits, quality gates, deployment checkouts
- The primary decision factor is a set of conditions and exceptions

Example:

```python
@approval_gate(layout="procedure_signoff")
def compliance_signoff(state):
    return {
        "subject": "Q2 compliance audit",
        "checklist": [
            {"item": "API security scan passed", "checked": True},
            {"item": "Data privacy review complete", "checked": True},
            {"item": "Exception: Third-party dependency has CVE", "checked": False}
        ]
    }
```

## Troubleshooting

### "No policy matched" — 400 error

**Problem**: Submitting an interrupt returns a 400 error with "No policy matched".

**Cause**: No policy rule's `when` expression matched, and `DEFAULT_APPROVER_EMAIL` is not set.

**Solution**:
1. Check your policy YAML syntax (indentation, field names)
2. Verify the interrupt payload includes the fields referenced in `when` expressions
3. Test your expression: does `amount.value >= 100` match? Missing fields evaluate to `false`.
4. Add a catch-all rule at the end:
   ```yaml
   - name: fallback
     when: "true"  # Always matches
     approvers:
       any_of: [default_approver_id]
   ```

### Notifications not sending

**Problem**: Approver doesn't receive Slack or email notification.

**Cause**: Notification config is missing or disabled.

**Solution**:
1. Check env vars: `SLACK_BOT_TOKEN`, `SMTP_HOST`, etc.
2. View notification attempts: query the `notification_attempts` table
   ```sql
   SELECT * FROM notification_attempts WHERE approval_id = '...' ORDER BY created_at DESC;
   ```
3. Check logs: `docker compose logs server | grep notification`
4. For Slack: verify bot has `chat:write`, `users:read`, `channels:read` scopes
5. For Email: test SMTP config manually:
   ```python
   import smtplib
   with smtplib.SMTP("smtp.example.com", 587) as s:
       s.starttls()
       s.login("user", "pass")
       print("SMTP OK")
   ```

### Timeout not firing

**Problem**: Approval sits pending indefinitely, doesn't escalate at timeout.

**Cause**: Worker service is not running, or no timeout is configured.

**Solution**:
1. Check worker is running: `docker compose logs worker`
2. Add timeout to your policy rule:
   ```yaml
   - name: my_rule
     when: "..."
     approvers: ...
     timeout: 4h
     on_timeout: escalate
     escalate_to: backup_approver
   ```
3. Verify escalate_to points to a valid approver in `approvers.yaml`

### "Approval not found" when opening approval URL

**Problem**: Browser shows 404 when clicking the approval link.

**Cause**: Approval ID is wrong, or the approval was created in a different environment.

**Solution**:
1. Check the approval URL format: `http://localhost:3000/a/{approval_id}` (UUIDs only in M2a)
2. Verify the approval exists: query the database
   ```sql
   SELECT id, status FROM approvals WHERE id = '550e8400-e29b-41d4-a716-446655440000';
   ```
3. Ensure the UI and server are both running and connected

### Agent not resuming after decision

**Problem**: Agent submitted interrupt, approver decided, but agent thread is still paused.

**Cause**: Agent is not polling, or polling timed out.

**Solution**:
1. Check agent logs for errors: `uv run python dogfood.py 2>&1 | grep -i error`
2. Verify `DELIBERATE_SERVER_URL` and `DELIBERATE_API_KEY` are set in the agent's environment
3. Check server logs: `docker compose logs server | grep ERROR`
4. If polling timeout is too short, increase `timeout_seconds` in the decorator:
   ```python
   @approval_gate(layout="...", timeout_seconds=7200)  # 2 hours
   ```

### Tests failing locally

**Problem**: Running `pytest` shows database connection errors.

**Solution**:
1. Start Docker Compose: `docker compose up -d`
2. Set `DATABASE_URL` environment variable before running tests:
   ```bash
   export DATABASE_URL=postgresql+asyncpg://deliberate:deliberate@localhost:5432/deliberate
   ```
3. For the SDK: `cd sdk && uv run pytest`
4. For the server: `cd server && uv run pytest`

## Next Steps

- **Read the PRD** — [Product Requirements Document](./PRD.md) for full architecture and design decisions
- **Explore layouts** — [Layouts guide](./LAYOUTS.md) to understand each built-in layout
- **Build a policy** — [Policy guide](./POLICIES.md) for writing complex routing rules
- **Set up notifications** — [Notifications guide](./NOTIFICATIONS.md) for Slack, Email, Webhook
- **Audit your approvals** — [Ledger guide](./LEDGER.md) for querying and exporting audit trails
- **Deploy to production** — [Deployment guide](./DEPLOYMENT.md) for Docker, Kubernetes, managed platforms

## Support

- **Discord** — [Join the community](https://discord.gg/deliberate)
- **GitHub Issues** — [Report a bug](https://github.com/your-handle/deliberate/issues)
- **Email** — `beomwookang@gmail.com`

---

*Built with love by [Beomwoo Kang](https://github.com/your-handle).*
