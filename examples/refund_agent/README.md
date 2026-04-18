# Refund Agent Example

A minimal LangGraph agent that demonstrates Deliberate's `@approval_gate` decorator.

## Prerequisites

- Docker and Docker Compose
- Python 3.11+
- The Deliberate stack running locally

## Setup

### 1. Generate a secret key and API key

```bash
# Generate SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate an API key for the SDK
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Create a `.env` file in the repo root

```bash
SECRET_KEY=<your-secret-key>
DEFAULT_APPROVER_EMAIL=you@example.com
```

### 3. Start the Deliberate stack

```bash
cd <repo-root>
docker compose up -d
```

### 4. Set the API key hash in the database

The default application is seeded with a placeholder API key hash. Update it:

```bash
# Replace <your-api-key> with the key you generated
python -c "
import hashlib
key = '<your-api-key>'
print(hashlib.sha256(key.encode()).hexdigest())
" | xargs -I{} docker exec deliberate-postgres-1 psql -U deliberate -c \
  "UPDATE applications SET api_key_hash = '{}' WHERE id = 'default';"
```

### 5. Install and run the agent

```bash
cd examples/refund_agent
pip install -e . -e ../../sdk

# Set SDK environment variables
export DELIBERATE_SERVER_URL=http://localhost:4000
export DELIBERATE_API_KEY=<your-api-key>
export DELIBERATE_UI_URL=http://localhost:3000

python agent.py
```

## What happens

1. The agent classifies the refund request (populates reasoning + evidence).
2. The `approve_refund` node hits the `@approval_gate` — the SDK submits the payload to the server and starts polling.
3. The server logs the approval URL: `[APPROVAL_URL] http://localhost:3000/a/<uuid>`
4. The agent also prints the URL to stdout.
5. Open the URL in your browser to see the `financial_decision` layout.
6. Submit a decision (approve/reject/etc.) with a rationale.
7. The SDK detects the decision, sends a resume ACK, and the agent continues.
8. If approved, the agent prints "REFUND PROCESSED" with the details.

## End-to-end flow

```
Agent starts
    └─ classify → populates reasoning + evidence
    └─ approve_refund (@approval_gate)
        └─ SDK POSTs to POST /interrupts
        └─ Server creates interrupt + approval rows
        └─ Server logs [APPROVAL_URL]
        └─ SDK polls GET /approvals/{id}/status every 2s
        └─ (You open the URL and submit a decision)
        └─ Server records decision + ledger entry
        └─ SDK sees status=decided, sends resume ACK
    └─ process_refund → prints result
Agent completes
```
