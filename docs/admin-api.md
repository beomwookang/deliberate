# Admin REST API Reference

The Deliberate Admin REST API lets you manage policies, approvers, groups, and API keys programmatically — without editing YAML files. All admin endpoints require an API key with the appropriate scope passed in the `X-Deliberate-API-Key` header.

For scope definitions and role bundles see [RBAC and API Key Management](./rbac.md).

---

## Authentication

Every admin API request must include:

```
X-Deliberate-API-Key: dlb_ak_<your-key>
```

The bootstrap admin key (`ADMIN_BOOTSTRAP_KEY` env var) has full admin access and can be used to create scoped keys for other services.

**Error responses:**

| Status | Meaning |
|---|---|
| 401 | Missing or invalid API key |
| 403 | Key does not have the required scope |
| 404 | Resource not found |
| 409 | Conflict (duplicate ID) |
| 422 | Request body validation failed |

---

## Policies

### POST /policies

Create a new policy. Required scope: `policies:write`.

```bash
curl -X POST http://localhost:4000/policies \
  -H "X-Deliberate-API-Key: dlb_ak_..." \
  -H "Content-Type: application/json" \
  -d '{
    "name": "refund_approval",
    "matches": {
      "layout": "financial_decision"
    },
    "rules": [
      {
        "name": "auto_approve_small",
        "when": "amount.value < 100",
        "action": "auto_approve",
        "rationale": "Below auto-approve threshold"
      },
      {
        "name": "standard",
        "when": "amount.value >= 100 and amount.value < 5000",
        "approvers": { "any_of": ["finance_lead"] },
        "timeout": "4h",
        "on_timeout": "escalate",
        "escalate_to": "finance_lead",
        "notify": ["email", "slack"]
      },
      {
        "name": "high_value",
        "when": "amount.value >= 5000",
        "approvers": { "all_of": ["finance_lead", "cfo"] },
        "timeout": "8h",
        "on_timeout": "fail",
        "notify": ["email", "slack", "webhook"]
      }
    ]
  }'
```

Response (201):

```json
{
  "name": "refund_approval",
  "version": 1,
  "created_at": "2026-04-23T10:00:00Z",
  "updated_at": "2026-04-23T10:00:00Z"
}
```

### GET /policies

List all policies. Required scope: `policies:read`.

```bash
curl http://localhost:4000/policies \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

Response (200):

```json
[
  {
    "name": "refund_approval",
    "version": 2,
    "rules_count": 3,
    "created_at": "2026-04-23T10:00:00Z",
    "updated_at": "2026-04-23T11:00:00Z"
  }
]
```

### GET /policies/{name}

Get a policy by name. Required scope: `policies:read`.

```bash
curl http://localhost:4000/policies/refund_approval \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

Response (200): Full policy object including all rules.

### PUT /policies/{name}

Replace a policy. Creates a new version. Required scope: `policies:write`.

```bash
curl -X PUT http://localhost:4000/policies/refund_approval \
  -H "X-Deliberate-API-Key: dlb_ak_..." \
  -H "Content-Type: application/json" \
  -d '{ ... full policy body ... }'
```

Response (200):

```json
{
  "name": "refund_approval",
  "version": 3,
  "updated_at": "2026-04-23T12:00:00Z"
}
```

### DELETE /policies/{name}

Delete a policy. Required scope: `policies:write`. Returns HTTP 204.

```bash
curl -X DELETE http://localhost:4000/policies/refund_approval \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

Note: Deleting a policy does not affect existing pending approvals that were created under that policy.

### POST /policies/{name}/test

Test a policy against a sample payload to see which rule would match. Required scope: `policies:read`.

```bash
curl -X POST http://localhost:4000/policies/refund_approval/test \
  -H "X-Deliberate-API-Key: dlb_ak_..." \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Refund for order #123",
    "layout": "financial_decision",
    "amount": { "value": 250.00, "currency": "USD" },
    "customer": { "id": "C-001", "display_name": "Alice Johnson" }
  }'
```

Response (200):

```json
{
  "matched_rule": "standard",
  "action": "route_to_approvers",
  "approvers": {
    "mode": "any_of",
    "resolved": [
      { "id": "finance_lead", "email": "priya@example.com", "display_name": "Priya Sharma" }
    ]
  },
  "timeout": "4h",
  "on_timeout": "escalate",
  "notify": ["email", "slack"]
}
```

If no rule matches:

```json
{
  "matched_rule": null,
  "error": "No rule matched the provided payload"
}
```

### GET /policies/{name}/versions

List all historical versions of a policy. Required scope: `policies:read`.

```bash
curl http://localhost:4000/policies/refund_approval/versions \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

Response (200):

```json
[
  {
    "version": 3,
    "updated_at": "2026-04-23T12:00:00Z",
    "updated_by": "admin"
  },
  {
    "version": 2,
    "updated_at": "2026-04-23T11:00:00Z",
    "updated_by": "operator-key"
  },
  {
    "version": 1,
    "created_at": "2026-04-23T10:00:00Z",
    "created_by": "seed"
  }
]
```

---

## Approvers

### POST /approvers

Create an approver. Required scope: `approvers:write`.

```bash
curl -X POST http://localhost:4000/approvers \
  -H "X-Deliberate-API-Key: dlb_ak_..." \
  -H "Content-Type: application/json" \
  -d '{
    "id": "finance_lead",
    "email": "priya@example.com",
    "display_name": "Priya Sharma",
    "out_of_office": {
      "active": false,
      "from": null,
      "until": null,
      "delegate_to": null
    }
  }'
```

Response (201):

```json
{
  "id": "finance_lead",
  "email": "priya@example.com",
  "display_name": "Priya Sharma",
  "out_of_office": { "active": false },
  "created_at": "2026-04-23T10:00:00Z"
}
```

### GET /approvers

List all approvers. Required scope: `approvers:read`.

```bash
curl http://localhost:4000/approvers \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

Response (200): Array of approver objects.

### GET /approvers/{id}

Get a single approver by ID. Required scope: `approvers:read`.

```bash
curl http://localhost:4000/approvers/finance_lead \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

### PUT /approvers/{id}

Update an approver. Required scope: `approvers:write`.

```bash
curl -X PUT http://localhost:4000/approvers/finance_lead \
  -H "X-Deliberate-API-Key: dlb_ak_..." \
  -H "Content-Type: application/json" \
  -d '{
    "email": "priya@example.com",
    "display_name": "Priya Sharma",
    "out_of_office": {
      "active": true,
      "from": "2026-05-01",
      "until": "2026-05-10",
      "delegate_to": "cfo"
    }
  }'
```

Response (200): Updated approver object.

### DELETE /approvers/{id}

Delete an approver. Required scope: `approvers:write`. Returns HTTP 204.

```bash
curl -X DELETE http://localhost:4000/approvers/finance_lead \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

Note: Deleting an approver does not affect pending approvals that reference them.

---

## Groups

### POST /groups

Create a group. Required scope: `groups:write`.

```bash
curl -X POST http://localhost:4000/groups \
  -H "X-Deliberate-API-Key: dlb_ak_..." \
  -H "Content-Type: application/json" \
  -d '{
    "id": "finance_team",
    "display_name": "Finance Team",
    "members": ["finance_lead", "cfo"]
  }'
```

Response (201):

```json
{
  "id": "finance_team",
  "display_name": "Finance Team",
  "members": ["finance_lead", "cfo"],
  "created_at": "2026-04-23T10:00:00Z"
}
```

### GET /groups

List all groups. Required scope: `groups:read`.

```bash
curl http://localhost:4000/groups \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

### GET /groups/{id}

Get a group by ID including resolved member details. Required scope: `groups:read`.

```bash
curl http://localhost:4000/groups/finance_team \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

Response (200):

```json
{
  "id": "finance_team",
  "display_name": "Finance Team",
  "members": [
    { "id": "finance_lead", "email": "priya@example.com", "display_name": "Priya Sharma" },
    { "id": "cfo", "email": "cfo@example.com", "display_name": "Alex Chen" }
  ]
}
```

### DELETE /groups/{id}

Delete a group. Required scope: `groups:write`. Returns HTTP 204.

```bash
curl -X DELETE http://localhost:4000/groups/finance_team \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

---

## API Keys

### POST /api-keys

Create a new API key. Required scope: `api_keys:write`. The `admin` role (or the `ADMIN_BOOTSTRAP_KEY`) is needed to create keys with broad scopes.

```bash
curl -X POST http://localhost:4000/api-keys \
  -H "X-Deliberate-API-Key: dlb_ak_..." \
  -H "Content-Type: application/json" \
  -d '{
    "name": "refund-agent-prod",
    "role": "agent",
    "description": "Production key for the refund processing agent"
  }'
```

Or specify scopes directly instead of a role:

```bash
curl -X POST http://localhost:4000/api-keys \
  -H "X-Deliberate-API-Key: dlb_ak_..." \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ci-readonly",
    "scopes": ["policies:read", "approvers:read", "groups:read"]
  }'
```

Response (201):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "refund-agent-prod",
  "key": "dlb_ak_Xk9mT3hQw...",
  "scopes": ["interrupts:write", "approvals:read"],
  "description": "Production key for the refund processing agent",
  "created_at": "2026-04-23T10:00:00Z"
}
```

The `key` field is returned once only. Store it immediately.

**Request body fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Human-readable name for the key |
| `role` | string | no | Predefined role: `agent`, `readonly`, `operator`, `admin` |
| `scopes` | array | no | Explicit scope list (used if `role` is not provided) |
| `extra_scopes` | array | no | Additional scopes to add on top of a role |
| `description` | string | no | Notes about what this key is used for |

### GET /api-keys

List all API keys. Returns metadata only — the raw key value is never returned after creation. Required scope: `api_keys:read`.

```bash
curl http://localhost:4000/api-keys \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

Response (200):

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "refund-agent-prod",
    "scopes": ["interrupts:write", "approvals:read"],
    "description": "Production key for the refund processing agent",
    "created_at": "2026-04-23T10:00:00Z",
    "last_used_at": "2026-04-23T11:30:00Z"
  }
]
```

### DELETE /api-keys/{id}

Revoke an API key immediately. Required scope: `api_keys:write`. Returns HTTP 204.

```bash
curl -X DELETE http://localhost:4000/api-keys/550e8400-e29b-41d4-a716-446655440000 \
  -H "X-Deliberate-API-Key: dlb_ak_..."
```

After revocation, any request using the revoked key receives HTTP 401.
