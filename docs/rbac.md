# RBAC and API Key Management

Deliberate uses scope-based access control. Every API key carries a set of scopes that determine which endpoints it can call. There is no role concept at the server level — roles are predefined scope bundles provided as a convenience when creating keys.

---

## Scopes

| Scope | Description |
|---|---|
| `interrupts:write` | Submit interrupts from agent code |
| `approvals:read` | Read approval status and payload |
| `ledger:read` | Query and export the audit ledger |
| `policies:read` | List and fetch policies |
| `policies:write` | Create, update, and delete policies |
| `approvers:read` | List and fetch approvers |
| `approvers:write` | Create, update, and delete approvers |
| `groups:read` | List and fetch groups |
| `groups:write` | Create and delete groups |
| `api_keys:read` | List API keys (redacted) |
| `api_keys:write` | Create and revoke API keys |

Endpoints that require a scope return HTTP 403 if the key does not carry it. Endpoints with no scope listed in this table are public (health, metrics, auth flows, approver decision submission).

---

## Predefined Roles

Roles are shorthand for common scope combinations. Pass a `role` when creating an API key instead of listing scopes individually.

| Role | Scopes Granted |
|---|---|
| `agent` | `interrupts:write`, `approvals:read` |
| `readonly` | `policies:read`, `approvers:read`, `groups:read`, `ledger:read`, `api_keys:read` |
| `operator` | All `readonly` scopes + `policies:write`, `approvers:write`, `groups:write` |
| `admin` | All scopes |

You can override or extend scopes after specifying a role:

```json
{
  "name": "ci-agent",
  "role": "agent",
  "extra_scopes": ["ledger:read"]
}
```

---

## API Key Format

All API keys issued by Deliberate have the format:

```
dlb_ak_<random>
```

The `<random>` portion is a 32-byte URL-safe base64 string generated with `secrets.token_urlsafe(32)`. The full raw key is returned once on creation and never stored. The server stores only a SHA-256 hash of the raw key.

---

## Key Lifecycle

### Create a key

```bash
curl -X POST http://localhost:4000/api-keys \
  -H "X-Deliberate-API-Key: ${ADMIN_BOOTSTRAP_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "refund-agent-prod",
    "role": "agent",
    "description": "Key for the refund processing agent in production"
  }'
```

Response:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "refund-agent-prod",
  "key": "dlb_ak_Xk9mT3...",
  "scopes": ["interrupts:write", "approvals:read"],
  "created_at": "2026-04-23T10:00:00Z"
}
```

The `key` field is shown only in this response. Store it immediately in your secrets manager.

### Use a key

Pass the raw key in the `X-Deliberate-API-Key` header on every request:

```bash
curl -X POST http://localhost:4000/interrupts \
  -H "X-Deliberate-API-Key: dlb_ak_Xk9mT3..." \
  -H "Content-Type: application/json" \
  -d '{ ... }'
```

### List keys

Returns key metadata. The raw key and its hash are never returned after creation.

```bash
curl http://localhost:4000/api-keys \
  -H "X-Deliberate-API-Key: ${ADMIN_BOOTSTRAP_KEY}"
```

Response:

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "refund-agent-prod",
    "scopes": ["interrupts:write", "approvals:read"],
    "created_at": "2026-04-23T10:00:00Z",
    "last_used_at": "2026-04-23T11:30:00Z"
  }
]
```

### Rotate a key

Key rotation is create-then-revoke:

1. Create a new key with the same role/scopes.
2. Update the new key value in your secrets manager and redeploy the service that uses it.
3. Verify the new key is working.
4. Revoke the old key.

```bash
# Step 1: Create new key
NEW_KEY=$(curl -s -X POST http://localhost:4000/api-keys \
  -H "X-Deliberate-API-Key: ${ADMIN_BOOTSTRAP_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"name": "refund-agent-prod-v2", "role": "agent"}' | jq -r '.key')

# Step 4: Revoke old key by ID
curl -X DELETE http://localhost:4000/api-keys/550e8400-e29b-41d4-a716-446655440000 \
  -H "X-Deliberate-API-Key: ${ADMIN_BOOTSTRAP_KEY}"
```

### Revoke a key

```bash
curl -X DELETE http://localhost:4000/api-keys/{id} \
  -H "X-Deliberate-API-Key: ${ADMIN_BOOTSTRAP_KEY}"
```

Response: HTTP 204 No Content. The key is immediately invalidated; any further requests using it receive HTTP 401.

---

## Bootstrap Key

The `ADMIN_BOOTSTRAP_KEY` environment variable provides a root admin credential for initial setup. It is not stored in the database — it is verified directly from the environment on each request.

**Responsibilities of the bootstrap key:**
- Create the first scoped API keys.
- Seed initial policies, approvers, and groups.
- Rotate API keys for other services.

**Security recommendations:**
- Store `ADMIN_BOOTSTRAP_KEY` in a secrets manager, not in `.env` files committed to version control.
- Use a separate scoped `admin`-role key for day-to-day administrative tasks; reserve `ADMIN_BOOTSTRAP_KEY` for break-glass scenarios.
- Rotate `ADMIN_BOOTSTRAP_KEY` by updating the environment variable and restarting the server.
- Audit access to `ADMIN_BOOTSTRAP_KEY` as you would a root database credential.

---

## Security Recommendations

- **Principle of least privilege.** Issue agent keys with the `agent` role only. Do not issue `admin`-role keys to automated systems.
- **One key per service.** Create separate keys for each agent, CI system, and integration. This allows individual revocation without affecting others.
- **Rotate on personnel change.** When a team member with key access leaves, rotate any keys they may have seen.
- **Never commit keys.** Use environment variables or a secrets manager. Add `dlb_ak_` patterns to your `.gitignore` or secret scanning rules.
- **Monitor for anomalies.** Alert on repeated 401 responses from `/interrupts` (possible key brute-force or misconfiguration). Monitor `last_used_at` on keys that should be in active use.
- **Audit before revoking.** Check `last_used_at` and recent ledger entries before revoking a key to confirm the dependent service has been updated.
