# Deliberate Security Review and Threat Model

This document covers the security posture of the Deliberate server as of v1.0. It is intended for operators deploying Deliberate in production and for security reviewers auditing the codebase.

---

## 1. Threat Model (STRIDE)

### Spoofing

**SDK-to-server authentication (API key)**

The SDK authenticates to the server using an `X-Deliberate-API-Key` header. The server stores only the SHA-256 hash of the key (`api_key_hash` in the `applications` table). On each request the server hashes the incoming key with `hashlib.sha256` and compares to the stored hash using `hmac.compare_digest` to prevent timing attacks. Raw API keys are never stored.

**Approver identity (magic link)**

In v1.0 approvers authenticate via a magic link delivered to their email address. The magic link contains a short-lived JWT (`aud="approval"`, `exp=1h`) signed with the server's `SECRET_KEY`-derived JWT key. Visiting the link proves control of the email inbox. No password is required.

**Approval URL integrity**

Approval page URLs use signed JWT tokens (`/a/{jwt}`) generated with a key derived from `SECRET_KEY` via HKDF. Tokens are bound to the approver email, carry a configurable expiry, and are verified on the approval page. Raw UUIDs are also accepted for backward compatibility.

---

### Tampering

**Decision signatures**

When an approver submits a decision, the server computes an HMAC-SHA256 signature over the canonicalized decision fields (`approval_id`, `decision_type`, `decision_payload`, `approver_email`, `decided_at`) using a key derived from `SECRET_KEY` via HKDF. The signature is stored in the `decisions` table and embedded in the ledger entry. Any post-hoc modification to a decision row is detectable by re-verifying the signature.

**Ledger content hashing**

Each ledger entry has a `content_hash` (SHA-256 over the serialized `content` JSON) and a `signature` (HMAC-SHA256 of the content hash). The content is built before signing and never mutated after commit. The `prev_hash` field chains entries, making retrospective insertion detectable.

**Payload size cap**

The interrupt handler enforces a 1 MB payload cap (per PRD §4.3). Payloads exceeding this limit receive HTTP 413. This prevents oversized payloads from bypassing hash integrity checks or exhausting memory.

---

### Repudiation

**Append-only ledger**

`LedgerEntry` rows are never updated or deleted. The `resume_ack` endpoint writes to a separate `resume_events` table rather than mutating ledger content. The `prev_hash` chain makes retrospective insertion detectable.

**Content hash integrity**

Every ledger entry includes a SHA-256 hash of the full content JSON. The hash is independently verifiable by re-serializing the content. HMAC signature over the hash ties integrity to the server's `SECRET_KEY`.

**Audit trail**

Every significant action (interrupt received, auto-approved, decision submitted, timeout, escalation) writes a ledger entry. The `thread_id` and `trace_id` fields allow correlation with the originating agent run.

---

### Information Disclosure

**CORS policy**

The server is configured to allow all origins by default (`Access-Control-Allow-Origin: *`). In production, configure CORS restrictions at the reverse proxy level (nginx, Caddy, AWS API Gateway) to limit allowed origins to your approval UI domain.

**Payload exposure**

Interrupt payloads are stored in `interrupts.payload` (JSONB) and returned to the approval UI. Sensitive fields should not be included in payloads; use references to external storage (e.g., S3 pre-signed URLs) for sensitive documents per PRD §4.3.

**Ledger exposure**

The `GET /ledger` endpoint requires a valid API key and is intended for SDK use only. It is not exposed to the approver UI. In production, this endpoint should not be reachable from the public internet.

**Error messages**

Validation errors return field-level detail from Pydantic. Internal errors return generic messages. No stack traces are exposed in production responses.

---

### Denial of Service

**Payload size limits**

The 1 MB interrupt payload cap (enforced before any DB write) prevents large-payload attacks from reaching the database.

**Timeout worker**

The APScheduler timeout worker polls every 15 seconds for expired pending approvals. Expired approvals are either failed or escalated rather than left open indefinitely. This prevents unbounded accumulation of pending state.

**Rate limiting**

v1.0 has no built-in rate limiting. Operators should deploy a reverse proxy (nginx, Caddy, AWS API Gateway) with rate limiting in front of the server. The `/interrupts` endpoint is the highest-risk target since it creates database rows on every call.

**Database connection limits**

SQLAlchemy's async connection pool is bounded. Operators should configure `DATABASE_POOL_SIZE` and set a matching `max_connections` in PostgreSQL to prevent pool exhaustion under load.

---

### Elevation of Privilege

**No admin UI**

There is no admin interface in v1.0. All privileged operations (creating applications, rotating API keys) require direct database access.

**Approver identity verification**

Approvers can only submit decisions for approvals they receive via email. The approval UUID in the URL is the authorization token. Without the UUID (obtained from the email link), an attacker cannot guess or enumerate valid approval IDs.

**Policy engine isolation**

The policy expression evaluator is a purpose-built recursive descent parser. It does not use `eval()` or any dynamic code execution. Missing field access returns `false` rather than raising exceptions.

---

## 2. Key Management

### Key Derivation

All cryptographic keys are derived from a single `SECRET_KEY` environment variable using HKDF (HMAC-based Key Derivation Function) with SHA-256. Three derived keys are produced:

| Purpose | HKDF info label |
|---|---|
| JWT signing (magic links, approval tokens) | `b"deliberate-jwt"` |
| Decision HMAC signatures | `b"deliberate-hmac"` |
| Content hash signatures | `b"deliberate-content"` |

The `SECRET_KEY` itself is never used directly as a cryptographic key. The HKDF derivation is implemented in `deliberate_server/auth.py`.

### Key Requirements

- `SECRET_KEY` must be a cryptographically random value of at least 32 bytes.
- Generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- The server refuses to start if `SECRET_KEY` is empty.
- Never use predictable values (hostnames, UUIDs, dates).

### Key Rotation

Key rotation is a breaking operation in v1.0:

1. Generate a new `SECRET_KEY`.
2. Update the environment variable (or secrets manager).
3. Restart the server.

After rotation:
- All existing magic link tokens are immediately invalidated (JWT signature check fails).
- All existing signed approval URLs are invalidated.
- Existing decision HMAC signatures in the database will fail re-verification against the new key.
- The ledger content signature chain remains intact (historical entries are not re-signed).

**Recommendation:** Schedule key rotation during a maintenance window when no approvals are pending. Coordinate with SDK deployments to re-issue API keys after rotation if needed.

---

## 3. Authentication and Authorization

### SDK-to-Server: API Key

```
SDK → POST /interrupts
      Header: X-Deliberate-API-Key: <raw_key>

Server:
  hash = SHA-256(raw_key)
  stored_hash = applications.api_key_hash
  valid = hmac.compare_digest(hash, stored_hash)
```

API keys are generated at application registration time. The raw key is shown once and never stored. The SHA-256 hash is stored. There is currently no API key rotation endpoint; rotation requires a direct database update.

### Approver Identity: Magic Link

```
Server → email → approver@example.com
  Link: https://approvals.example.com/a/{approval_id}?token={jwt}

JWT claims:
  sub: approver_email
  aud: "approval"
  exp: now + 1h
  jti: random UUID (not yet tracked for replay prevention)
```

The magic link email is sent when an interrupt is created (if `notify: [email]` is configured in the policy). The JWT is validated on the approval page via `POST /auth/verify-approval-token`. JWT replay prevention (jti tracking) is planned for v1.1.

### Approval URLs

Approval URLs use signed JWT tokens (`/a/{jwt}`) with approver binding and expiry. Raw UUIDs are also accepted for backward compatibility. The token is verified by the approval page before rendering. jti replay prevention is planned for v1.1.

### No Role-Based Access Control

v1.0 has no RBAC. Any approver who receives a valid approval URL can submit a decision. Policy configuration is the primary access control mechanism: only approvers named in a policy rule will receive notification emails. However, there is no enforcement at the decision endpoint that checks whether the submitting approver matches the policy-assigned approver.

**Implication:** Anyone who obtains a valid approval UUID can submit a decision. The security model relies on keeping approval URLs confidential (delivered only via email to the designated approver).

---

## 4. Data Integrity

### Ledger Immutability

The `ledger_entries` table is append-only. No endpoint updates or deletes ledger rows. The `resume_ack` endpoint writes to `resume_events` (a separate table) and updates only operational columns (`resume_status`, `resume_latency_ms`) — not the `content` JSONB column.

### Content Hash Chain

Each ledger entry records:
- `content_hash`: SHA-256 of the serialized `content` JSON
- `prev_hash`: `content_hash` of the immediately preceding ledger entry (by `created_at`)
- `signature`: HMAC-SHA256(`content_hash`, derived key)

This chain allows independent verification that no entries have been inserted, reordered, or modified after the fact.

### Decision HMAC Signatures

Decision fields are signed before storage:
```python
fields = {
    "approval_id": str(approval_id),
    "decision_type": body.decision_type,
    "decision_payload": body.decision_payload,
    "approver_email": body.approver_email,
    "decided_at": now.isoformat(),
}
signature = HMAC-SHA256(canonical_json(fields), hmac_key)
```

The signature is stored in `decisions.signature` and embedded in `ledger_entries.content`.

### Schema Validation

Before writing a ledger entry, the server validates the constructed `ledger_content` dict against the SDK's `LedgerEntry` Pydantic schema. If validation fails, the transaction is aborted and HTTP 500 is returned. This prevents malformed ledger entries from being written to the database.

---

## 5. Known Limitations

| Limitation | Severity | Status |
|---|---|---|
| Single-tenant only | Medium | Planned for v1.1 |
| No rate limiting | High | Deploy reverse proxy with rate limiting |
| Magic link JWTs not tracked for replay | Medium | Planned for v1.1 |
| Approval URLs use raw UUIDs (no expiry) | Medium | Implemented — signed JWT tokens in v1.0 |
| No RBAC on decision endpoint | Medium | Planned for v1.1 |
| No IP allowlisting | Low | Configurable at reverse proxy level |
| CORS allows all origins by default | Medium | Configure at reverse proxy in production |
| API key rotation requires DB access | Low | Planned for v1.1 |
| No jti replay prevention on magic links | Medium | Planned for v1.1 |
| Escalation loop guard absent | Low | Implemented — max-depth check in v1.0 |
| Secret rotation invalidates pending approvals | Medium | Accepted trade-off for v1.0 |

---

## 6. Production Deployment Recommendations

### Secret Key

```bash
# Generate a strong SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Store in a secrets manager (AWS Secrets Manager, HashiCorp Vault, Doppler). Do not commit to version control or embed in Docker images.

### TLS and Reverse Proxy

Always deploy behind a reverse proxy that terminates TLS:

```nginx
server {
    listen 443 ssl;
    server_name api.deliberate.example.com;

    ssl_certificate /etc/ssl/certs/server.crt;
    ssl_certificate_key /etc/ssl/private/server.key;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=deliberate:10m rate=10r/s;
    limit_req zone=deliberate burst=20 nodelay;

    location / {
        proxy_pass http://deliberate-server:8000;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Host $host;
    }
}
```

### CORS Configuration

The server allows all origins by default. In production, restrict allowed origins at the reverse proxy level rather than in the application. For example, with nginx:

```nginx
add_header Access-Control-Allow-Origin "https://approvals.example.com";
add_header Access-Control-Allow-Methods "GET, POST, OPTIONS";
add_header Access-Control-Allow-Headers "X-Deliberate-API-Key, Content-Type";
```

### Database Security

- Use a dedicated PostgreSQL user with least-privilege access (SELECT, INSERT, UPDATE on application tables; no DROP, TRUNCATE, CREATE).
- Enable `ssl=require` in `DATABASE_URL`.
- Set `max_connections` in PostgreSQL to match the server's pool size plus headroom.

### Key Rotation Schedule

- Rotate `SECRET_KEY` at least quarterly.
- Rotate API keys when team members with access leave.
- Schedule rotation during low-traffic windows.
- Notify approvers of upcoming rotation if pending approvals exist.

### Monitoring

- Alert on repeated 401 responses from `/interrupts` (API key brute-force attempts).
- Alert on spikes in `/interrupts` request rate (potential abuse).
- Monitor `notification_attempts` table for persistent delivery failures.
- Set up ledger entry count alerts to detect unexpected gaps in the hash chain.
