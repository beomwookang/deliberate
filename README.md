<div align="center">

<!-- TODO: Add banner image at docs/assets/banner.png -->

# Deliberate

### The approval layer for LangGraph agents

[**Quickstart**](./docs/quickstart.md) · [**Docs**](./docs/) · [**Report a bug**](https://github.com/beomwookang/deliberate/issues)

![MIT License](https://img.shields.io/badge/License-MIT-E11311.svg)
![GitHub Stars](https://img.shields.io/github/stars/beomwookang/deliberate?style=social)

Your LangGraph agent calls `interrupt()`. Now what?

Deliberate turns it into an approval request a non-engineer can actually answer — with notifications, timeouts, structured audit trails, and UIs built for the people who actually sign off.

<!-- TODO: Add hero GIF at docs/assets/hero.gif showing the approval flow -->

</div>

---

## The gap LangGraph leaves open

LangGraph made `interrupt()` a first-class primitive. That solved the *runtime* half of human-in-the-loop — the graph pauses, state is checkpointed, and execution resumes with `Command(resume=...)`.

The *organizational* half is still yours to build:

- **Nobody gets notified.** The thread sits in the checkpointer. If your approver isn't watching the terminal, they don't know you're waiting on them.
- **Nothing times out.** A graph paused 3 weeks ago is indistinguishable from one paused 30 seconds ago.
- **There's no audit log.** State is persisted, but *who* decided, *when*, *why*, *with what context* — that record doesn't exist unless you build it.
- **Your approver is probably not an engineer.** But the only interface LangGraph gives them is your Python REPL.

Deliberate fills that gap — everything between *your agent paused* and *your agent resumes*.

---

## Quickstart

**1. Run Deliberate**

```bash
git clone https://github.com/beomwookang/deliberate.git
cd deliberate
docker compose up
```

Deliberate is running on `http://localhost:4000`.

**2. Install the SDK**

```bash
pip install deliberate
```

**3. Wrap your LangGraph node**

```python
from deliberate import approval_gate
from langgraph.types import interrupt

@approval_gate(
    layout="financial_decision",
    notify=["email:finance@acme.com", "slack:#finance-approvals"],
    policy="policies/refund.yaml",
)
def process_refund(state):
    return interrupt({
        "customer": state.customer,
        "amount": state.amount,
        "agent_reasoning": state.reasoning,
        "evidence": state.evidence,
    })
```

That's it. When the graph reaches this node, Deliberate routes the approval, notifies the right person, and waits — then hands the decision back to your graph.

See the [full quickstart](./docs/quickstart.md) or grab a [working example](./examples/refund_agent).

---

## Built-in layouts for HITL-critical domains

Different decisions need different information architecture. A finance lead approving a refund doesn't need the same layout as a legal reviewer redlining a contract. Deliberate ships with 6 layouts tuned for the domains where HITL matters most.

| Layout | Use case | Key elements |
|--------|----------|-------------|
| `financial_decision` | Refunds, expense approvals, budget requests | Amount card, customer info, evidence table |
| `document_review` | Contracts, policies, legal redlines | Document link, flagged clauses, clause highlights |
| `procedure_signoff` | Audit steps, compliance checks, quality gates | Checklist with pass/fail, exceptions, standards ref |
| `data_access` | Sensitive data access, export approvals | Resource/scope, risk level badge, requester info |
| `content_moderation` | Generated-content review, publish approvals | Content preview, flagged items, policy references |
| `code_deployment` | Automated deploys, infra changes | Diff summary, test results bar, rollback plan |

<!-- TODO: Add screenshot for each layout in docs/assets/layout-*.png -->

Need something else? [Build a custom layout](./docs/custom-layouts.md) — layouts are just React components that consume a typed payload schema.

---

## Features

- **Multi-channel notifications** — Slack, Email, or Webhook. Pick one, or fan out to all three.
- **Timeouts and escalation** — Approver didn't respond in 4h? Auto-escalate to the backup or fail gracefully.
- **YAML policy routing** — Declare who approves what based on payload. Auto-approve small amounts, require two sign-offs for big ones.
- **Audit ledger** — Append-only, hash-chained, with JSON/CSV export. Every decision structured and tamper-evident.
- **OTLP export** — Feed ledger events into Langfuse, Phoenix, or any OTLP-compatible collector.
- **Prometheus metrics** — `/metrics` endpoint with interrupts, decisions, duration, timeouts, escalations.
- **Approver identity** — Magic link email verification. No more `anonymous@` in your audit trail.
- **Mobile-first approver UI** — Because your finance lead approves from their phone in meetings.
- **LangGraph native** — Built directly on `interrupt()` and `Command(resume=...)`. No adapters, no abstractions to learn.

---

## How it works

```
LangGraph Agent                    Deliberate Server                 Approver
     |                                    |                            |
     |-- interrupt() + @approval_gate --> |                            |
     |                                    |-- evaluate YAML policy     |
     |                                    |-- notify (Slack/Email/WH) --> |
     |                                    |                            |
     |                                    |   <-- open signed link --- |
     |                                    |   <-- submit decision ---- |
     |                                    |                            |
     |   <-- Command(resume=decision) --- |-- write to ledger         |
     |                                    |                            |
```

1. The SDK captures the payload and posts it to Deliberate's server.
2. Deliberate evaluates your YAML policy to resolve approvers, timeout, and escalation rules.
3. Notifications fire to the configured channels with a signed JWT approval link.
4. The approver opens the link, sees the layout you configured, and submits a structured decision.
5. Deliberate writes the decision to the append-only ledger and resumes your graph.
6. Your agent picks up exactly where it paused.

The graph state lives in LangGraph's checkpointer. The approval state, audit trail, and policy evaluation live in Deliberate's Postgres. The two stay synchronized through the LangGraph thread ID.

---

## Relationship to LangGraph

Deliberate isn't a replacement for LangGraph's HITL primitives — it builds on them.

LangGraph gives you `interrupt()`, `Command(resume=...)`, and a checkpointer. That's the low-level runtime, and it's excellent. What LangGraph deliberately doesn't ship (by design, since every team's notification stack and audit requirements are different) is the layer that turns an interrupted thread into an actual request a human sees, responds to, and leaves a record of.

That layer is Deliberate. Use LangGraph's `interrupt()` anywhere — Deliberate only kicks in when you wrap a node with `@approval_gate`. Mix and match as you like.

---

## Project status

Deliberate is at **v1.0**. The core flow (SDK → server → notifications → approval UI → resume → ledger) works end-to-end. Self-hosting is supported. Managed cloud is not yet available.

### Documentation

- [Quickstart Guide](./docs/quickstart.md) — 15-minute install-to-first-approval
- [Custom Layouts](./docs/custom-layouts.md) — build your own approval layouts
- [Security & Threat Model](./docs/security.md) — STRIDE analysis, key management, production recommendations
- [Contributing](./CONTRIBUTING.md) — development setup and PR process

### Not planned (for now)

- Support for non-LangGraph agent frameworks. Our goal is to be the best approval layer for LangGraph specifically.
- BPMN-style multi-step workflows. If you need this, check out Camunda or Temporal.

---

## Related projects

- **[LangGraph](https://github.com/langchain-ai/langgraph)** — the agent runtime Deliberate builds on.
- **[Langfuse](https://github.com/langfuse/langfuse)** — LLM observability and tracing. Complementary: Langfuse records *what the agent did*; Deliberate records *what the human decided*.
- **[OpenTelemetry GenAI conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)** — the spec we align ledger exports to.

---

## Contributing

We welcome contributions. Start here:

- [Read CONTRIBUTING.md](./CONTRIBUTING.md) to set up a dev environment
- [Report bugs](https://github.com/beomwookang/deliberate/issues)
- [Vote on ideas](https://github.com/beomwookang/deliberate/discussions/categories/ideas) on GitHub Discussions

Good first issues are tagged [`good-first-issue`](https://github.com/beomwookang/deliberate/issues?q=is%3Aissue+label%3Agood-first-issue).

---

## License

MIT. See [LICENSE](./LICENSE).

---

<div align="center">

Built by [Beomwoo Kang](https://github.com/beomwookang).

</div>
