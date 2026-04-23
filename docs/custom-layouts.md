# Custom Layouts Guide

Layouts are the approval UI components that render interrupt payloads for human reviewers. Each layout is a React Server Component that receives the interrupt payload and renders a specialized decision interface.

Deliberate ships six built-in layouts:
- `financial_decision` — for monetary approval requests (refunds, purchases, transfers)
- `document_review` — for contract and document review workflows
- `procedure_signoff` — for checklist-based procedure approvals
- `data_access` — for data access requests (resource, scope, risk level)
- `content_moderation` — for flagged content review (flagged items, policy references)
- `code_deployment` — for deployment approvals (diff, test results, rollback plan)

This guide walks through creating a custom layout for your own approval type.

---

## 1. Layout Architecture

When an interrupt is submitted, the `layout` field in the `InterruptPayload` determines which React component renders the approval page.

**Flow:**

```
Agent submits interrupt → POST /interrupts (layout: "ticket_approval")
                        ↓
Server stores payload + layout in interrupts table
                        ↓
Approver visits /a/{approval_id}
                        ↓
page.tsx fetches payload → routes to TicketApprovalLayout
                        ↓
Approver submits decision → POST /approvals/{id}/decide
```

**Relevant files:**

- `ui/app/a/[approval_id]/page.tsx` — approval page: fetches payload, routes to layout
- `ui/components/layouts/{name}/index.tsx` — layout component
- `ui/components/layouts/financial_decision/index.tsx` — reference implementation

---

## 2. Payload Shape

The `InterruptPayload` type (defined in `sdk/src/deliberate/types.py`) is the base type. Your agent passes a `payload` dict that gets stored verbatim. The layout component receives this dict and is responsible for interpreting it.

Example payload for a ticket approval:

```python
payload = InterruptPayload(
    layout="ticket_approval",
    subject="Deploy to production: service-auth v2.3.1",
    amount=None,
    currency=None,
    customer_id="team-platform",
    agent_reasoning="Deployment includes 3 security patches. No breaking changes detected.",
    evidence=[
        {"label": "PR", "value": "#4821"},
        {"label": "CI Status", "value": "All checks passed"},
        {"label": "Risk Score", "value": "Low"},
    ],
)
```

Any additional fields can be added directly to the `payload` dict passed to `submit_interrupt`. They are stored as-is and available to your layout component.

---

## 3. Creating a Custom Layout

### Step 1: Define a TypeScript interface for your payload

Create the type definition. Conventionally this lives at the top of your layout component file:

```typescript
// ui/components/layouts/ticket_approval/index.tsx
interface TicketApprovalPayload {
  subject: string;
  customer_id: string;
  agent_reasoning: string | { summary: string; details: string[] };
  evidence?: Array<{ label: string; value: string }>;
  // Custom fields for your layout
  ticket_id: string;
  risk_score: "low" | "medium" | "high";
  deploy_target: string;
  rollback_plan?: string;
}
```

### Step 2: Create the component

Create `ui/components/layouts/ticket_approval/index.tsx`:

```typescript
import { DecisionForm } from "@/components/decision-form";

interface TicketApprovalPayload {
  subject: string;
  customer_id: string;
  agent_reasoning: string | { summary: string; details: string[] };
  evidence?: Array<{ label: string; value: string }>;
  ticket_id: string;
  risk_score: "low" | "medium" | "high";
  deploy_target: string;
  rollback_plan?: string;
}

interface Props {
  approvalId: string;
  payload: Record<string, unknown>;
  decisionOptions?: string[];
  rationaleCategories?: string[];
}

const RISK_COLORS = {
  low: "bg-green-100 text-green-800",
  medium: "bg-amber-100 text-amber-800",
  high: "bg-red-100 text-red-800",
};

export function TicketApprovalLayout({
  approvalId,
  payload,
  decisionOptions,
  rationaleCategories,
}: Props) {
  const p = payload as TicketApprovalPayload;
  const riskColor = RISK_COLORS[p.risk_score] ?? "bg-gray-100 text-gray-800";

  const reasoning =
    typeof p.agent_reasoning === "string"
      ? p.agent_reasoning
      : p.agent_reasoning?.summary ?? "";

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">{p.subject}</h1>
        <p className="text-sm text-gray-500 mt-1">
          Ticket {p.ticket_id} · Target: {p.deploy_target}
        </p>
      </div>

      {/* Risk badge */}
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-gray-700">Risk:</span>
        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${riskColor}`}>
          {p.risk_score.toUpperCase()}
        </span>
      </div>

      {/* Agent reasoning */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-blue-900 mb-1">Agent Reasoning</h2>
        <p className="text-sm text-blue-800">{reasoning}</p>
      </div>

      {/* Rollback plan */}
      {p.rollback_plan && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-1">Rollback Plan</h2>
          <p className="text-sm text-gray-600">{p.rollback_plan}</p>
        </div>
      )}

      {/* Evidence table */}
      {p.evidence && p.evidence.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Evidence</h2>
          <table className="w-full text-sm border border-gray-200 rounded-lg overflow-hidden">
            <tbody>
              {p.evidence.map((row, i) => (
                <tr key={i} className={i % 2 === 0 ? "bg-white" : "bg-gray-50"}>
                  <td className="px-4 py-2 font-medium text-gray-600 w-1/3">{row.label}</td>
                  <td className="px-4 py-2 text-gray-900">{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Decision form */}
      <DecisionForm
        approvalId={approvalId}
        decisionOptions={decisionOptions ?? [{ type: "approve", label: "Approve" }, { type: "reject", label: "Reject" }]}
        rationaleCategories={rationaleCategories ?? ["policy_compliant", "too_risky"]}
      />
    </div>
  );
}
```

### Step 3: Register the layout in the approval page

Open `ui/app/a/[approval_id]/page.tsx` and add your layout to the routing switch:

```typescript
// Add your import at the top:
import { TicketApprovalLayout } from "@/components/layouts/ticket_approval";

// Add your case in the layout routing block:
if (data.layout === "ticket_approval") {
  return (
    <TicketApprovalLayout
      approvalId={approvalId}
      payload={data.payload}
      decisionOptions={["approve", "request_changes", "reject"]}
      rationaleCategories={[
        "policy_compliant",
        "too_risky",
        "missing_rollback_plan",
        "needs_more_testing",
      ]}
    />
  );
}
```

### Step 4: Configure default decision options and rationale categories

Each layout has its own semantically appropriate decision options and rationale categories. These are passed as props from the approval page and rendered by `DecisionForm`. Choose options that make sense for your workflow:

| Layout type | Decision options | Rationale categories |
|---|---|---|
| financial_decision | approve, modify, escalate, reject | policy_compliant, amount_too_high, needs_review, fraud_suspected |
| document_review | approve, redline, reject | policy_compliant, legal_concern, missing_clause, requires_revision |
| procedure_signoff | sign_off, request_rework, escalate | all_steps_verified, step_failed, safety_concern |
| ticket_approval | approve, request_changes, reject | policy_compliant, too_risky, missing_rollback_plan |

### Step 5: Configure your policy to use the layout

In `server/config/policies.yaml`, create a rule that routes to your layout:

```yaml
name: deployment_approval
matches:
  layout: ticket_approval

rules:
  - name: all-deployments
    when: "true"
    approvers:
      any_of: [platform_leads]
    timeout: 1h
    on_timeout: escalate
    escalate_to: platform_leads_escalation
    notify: [email, slack]
```

---

## 4. Full Example: ticket_approval Layout

The complete working example is in `ui/components/layouts/ticket_approval/index.tsx` (created above).

**Agent side (Python):**

```python
from deliberate import approval_gate
from deliberate.types import InterruptPayload

@approval_gate
async def deploy_to_production(state, config=None):
    payload = InterruptPayload(
        layout="ticket_approval",
        subject=f"Deploy {state['service']} {state['version']} to production",
        agent_reasoning={
            "summary": f"Deployment risk assessment: {state['risk_score']}",
            "details": state["risk_factors"],
        },
        evidence=[
            {"label": "Ticket", "value": state["ticket_id"]},
            {"label": "CI Status", "value": state["ci_status"]},
            {"label": "Affected Services", "value": str(state["affected_count"])},
        ],
        # Custom fields (stored verbatim in payload)
        ticket_id=state["ticket_id"],
        risk_score=state["risk_score"],
        deploy_target=state["environment"],
        rollback_plan=state.get("rollback_plan"),
    )
    decision = await client.wait_for_decision(payload)
    return {"decision": decision}
```

**Result:** The approver sees a clean deployment approval UI with the risk badge, agent reasoning, rollback plan, and evidence table, then submits approve/request_changes/reject with a rationale.

---

## 5. Best Practices

**Responsive design.** Use the `max-w-2xl mx-auto` container pattern. Approval emails are opened on mobile; keep the layout functional at 375px width.

**Accessibility.** Use semantic HTML (`<table>`, `<h2>`, etc.). Ensure color is not the only indicator of meaning — pair color badges with text labels.

**Consistent styling.** Follow the color conventions used in built-in layouts:
- Blue (`bg-blue-50`) — agent reasoning
- Amber (`bg-amber-100`) — warnings, flagged items
- Green (`bg-green-100`) — positive indicators
- Red (`bg-red-100`) — high risk, rejections
- Gray (`bg-gray-50`) — neutral information

**Structured agent_reasoning.** The `agent_reasoning` field can be a plain string or a structured object `{ summary, details }`. Always handle both:

```typescript
const reasoning =
  typeof p.agent_reasoning === "string"
    ? p.agent_reasoning
    : p.agent_reasoning?.summary ?? "";
```

**Evidence table.** Use the `Array<{ label: string; value: string }>` pattern for evidence. This is consistent across all built-in layouts and makes payloads predictable.

**Avoid large payloads.** Per PRD §4.3, payloads are capped at 1 MB. For documents, store the content externally (S3, GCS) and include a signed URL in the payload instead of embedding the content.

**TypeScript safety.** Cast `payload: Record<string, unknown>` to your typed interface at the top of the component. Do not spread the raw payload into JSX props.
