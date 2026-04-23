# Contributing to Deliberate

Thank you for your interest in contributing. This document covers how to set up your environment, run tests, and submit changes.

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 16
- Docker & Docker Compose (for full-stack development)
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- [pnpm](https://pnpm.io/) (Node package manager)

## Development Setup

### Full stack (recommended)

```bash
cp .env.example .env
docker compose --profile dev up -d
```

This starts PostgreSQL, the FastAPI server, the APScheduler worker, the Next.js UI, and MailHog for email testing.

### Individual services

**Server**

```bash
cd server
uv pip install -e ".[dev]"
uv run uvicorn deliberate_server.main:app --reload --port 4000
```

**Worker**

```bash
cd server
uv run python -m deliberate_server.worker
```

**UI**

```bash
cd ui
pnpm install
pnpm dev
```

**SDK**

```bash
cd sdk
uv pip install -e ".[dev]"
```

## Running Tests

**SDK tests**

```bash
cd sdk
uv run pytest
```

**Server tests** (requires a running PostgreSQL instance)

```bash
cd server
uv run pytest
```

**UI type check and lint**

```bash
cd ui
pnpm typecheck
pnpm lint
```

## Code Style

### Python

We use [ruff](https://docs.astral.sh/ruff/) for formatting and linting, and [mypy](https://mypy.readthedocs.io/) for static typing.

```bash
cd server   # or sdk
ruff format src/ tests/
ruff check src/ tests/
mypy src/
```

All Python code must pass `mypy --strict`. CI will reject PRs with type errors.

### TypeScript / React

We use ESLint and the TypeScript compiler for static checks.

```bash
cd ui
pnpm lint
pnpm typecheck
```

No `any` casts without a comment explaining why. Match the existing patterns for Server vs Client Components (`"use client"` at the top only when required).

## Architecture Overview

See [PRD.md](PRD.md) for the full product specification. Key invariants:

- The **ledger** is the source of truth. Operational tables (`approvals`, `interrupts`) project from it.
- All business tables carry `application_id`, indexed as the leading column.
- The **policy expression language** is fixed — do not extend it without a PRD update.
- The **server** knows nothing about LangGraph internals; that belongs in the SDK only.

The repository is structured as three independent packages:

| Package | Language | Purpose |
|---------|----------|---------|
| `sdk/` | Python | `@approval_gate` decorator, `DeliberateClient` |
| `server/` | Python (FastAPI) | REST API, policy engine, notifications, worker |
| `ui/` | TypeScript (Next.js) | Approval review UI |

## Pull Request Process

**Branch naming:** `type/short-description` — e.g. `feat/slack-inline-approve`, `fix/timeout-race`.

**Commit style:** [Conventional Commits](https://www.conventionalcommits.org/) — `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.

**Required CI checks** (all must pass before merge):

- `sdk-check` — ruff, mypy, pytest
- `server-check` — ruff, mypy, pytest
- `ui-check` — ESLint, TypeScript, build

**PR guidelines:**

1. Keep PRs focused. One logical change per PR.
2. Add or update tests for any changed behavior.
3. Do not commit secrets. Use `.env.example` for new environment variables.

## Good First Issues

Look for issues labelled `good first issue` in the GitHub issue tracker. These are scoped to a single file or endpoint and include enough context to get started without deep knowledge of the full system.

## Questions

Open a GitHub Discussion or leave a comment on the relevant issue.
