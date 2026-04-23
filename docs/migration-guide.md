# Migration Guide: YAML Config to Database (M5)

Starting with M5, the Deliberate server treats the database as the source of truth for policies, approvers, and groups. YAML files (`approvers.yaml`, policy YAML files in `POLICIES_DIR`) are still supported as a seed mechanism, but the Admin REST API is now the authoritative interface for managing configuration at runtime.

This guide covers the transition from the YAML-first workflow (M1–M4) to the database-first workflow (M5+).

---

## What Changes

| Area | Before M5 | After M5 |
|---|---|---|
| Approver config | Edit `config/approvers.yaml`, hot-reloaded on change | Manage via `POST/PUT/DELETE /approvers`; YAML is seed-only |
| Policy config | Edit YAML files in `POLICIES_DIR`, hot-reloaded | Manage via `POST/PUT/DELETE /policies`; YAML is seed-only |
| Group config | Defined in `config/approvers.yaml` under `groups:` | Manage via `POST/DELETE /groups`; seeded from YAML |
| API keys | Single key from `DELIBERATE_API_KEY` env var | Scoped keys managed via `POST/DELETE /api-keys` |
| Policy testing | Manual (`curl` against live agent flow) | `POST /policies/{name}/test` endpoint |
| Policy versioning | Git history of YAML files | `GET /policies/{name}/versions` tracks DB changes |

---

## What Stays the Same

- The SDK and `@approval_gate` decorator are unchanged.
- All existing agent API endpoints are unchanged (`POST /interrupts`, `GET /approvals/{id}/status`, etc.).
- The `X-Deliberate-API-Key` header format is unchanged.
- Existing approval URLs, ledger entries, and decisions are unaffected.
- Docker Compose and environment variable names are unchanged (new optional variables added).
- YAML files still work for initial seeding; existing configs do not need to be deleted.

---

## Migration Steps

### 1. Run database migration 0006

Migration 0006 creates the `policies`, `approvers`, `groups`, and `api_keys` tables. It does not modify existing tables.

If you are running with Docker Compose, the migration runs automatically on server startup. If you are running the server directly:

```bash
cd server
uv run alembic upgrade head
```

Verify the migration completed:

```bash
docker compose logs server | grep "alembic"
# Expected: INFO  [alembic.runtime.migration] Running upgrade ... -> 0006
```

### 2. Set SEED_FROM_YAML=true (recommended)

Add `SEED_FROM_YAML=true` to your `.env` file and restart the server. The server will read your existing YAML files and import their contents into the database on startup (idempotent: existing rows are not duplicated).

```bash
# .env
SEED_FROM_YAML=true
```

```bash
docker compose up -d
```

Verify seeding completed:

```bash
docker compose logs server | grep "seed"
# Expected: INFO  Seeded N approvers, M groups, K policies from YAML
```

After seeding, you can verify the imported data:

```bash
# List approvers
curl http://localhost:4000/approvers \
  -H "X-Deliberate-API-Key: ${ADMIN_BOOTSTRAP_KEY}"

# List policies
curl http://localhost:4000/policies \
  -H "X-Deliberate-API-Key: ${ADMIN_BOOTSTRAP_KEY}"
```

### 3. Set ADMIN_BOOTSTRAP_KEY

The bootstrap key gives you initial admin access to create scoped API keys for your agents and services.

```bash
# Generate a strong bootstrap key
python -c "import secrets; print('dlb_ak_' + secrets.token_urlsafe(32))"
```

Add it to `.env`:

```bash
ADMIN_BOOTSTRAP_KEY=dlb_ak_<your-generated-key>
```

Restart the server, then create a scoped agent key:

```bash
curl -X POST http://localhost:4000/api-keys \
  -H "X-Deliberate-API-Key: ${ADMIN_BOOTSTRAP_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-agent", "role": "agent"}'
```

Update `DELIBERATE_API_KEY` in your agent's environment with the returned key.

### 4. Manage configuration via the API going forward

From this point, use the Admin REST API to add, update, or remove policies, approvers, and groups. YAML files can remain on disk as a reference but will not be re-read after the initial seed (unless the server is restarted with `SEED_FROM_YAML=true` and rows have been removed from the DB, which would trigger a re-seed).

```bash
# Add a new approver
curl -X POST http://localhost:4000/approvers \
  -H "X-Deliberate-API-Key: ${ADMIN_BOOTSTRAP_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"id": "legal_lead", "email": "legal@example.com", "display_name": "Legal Lead"}'

# Update an existing policy
curl -X PUT http://localhost:4000/policies/refund_approval \
  -H "X-Deliberate-API-Key: ${ADMIN_BOOTSTRAP_KEY}" \
  -H "Content-Type: application/json" \
  -d '{ ... updated policy body ... }'
```

See [Admin API Reference](./admin-api.md) for the full endpoint documentation.

---

## Rollback

If you need to revert to the YAML-only workflow:

1. Stop the server.
2. Remove `SEED_FROM_YAML` and `ADMIN_BOOTSTRAP_KEY` from `.env`.
3. Run `alembic downgrade -1` to roll back migration 0006.
4. Restart the server.

The YAML hot-reload behavior from M1–M4 will resume. Any changes made via the Admin API after migration will be lost.

```bash
cd server
uv run alembic downgrade -1
docker compose up -d
```

---

## Notes

- **SEED_FROM_YAML is idempotent.** Running with `SEED_FROM_YAML=true` multiple times is safe. The server checks for existing rows by ID before inserting. Rows modified via the API after seeding will not be overwritten.
- **YAML files are not deleted by the migration.** They remain on disk and can still be used as documentation or for rollback.
- **Policy versions.** Each time a policy is created or updated via the API, a version snapshot is written. Use `GET /policies/{name}/versions` to see the full change history.
- **Existing API key behavior.** The `DELIBERATE_API_KEY` environment variable (used by the SDK) still works as a legacy agent key with `agent`-role scopes. You can migrate to DB-managed keys incrementally.
