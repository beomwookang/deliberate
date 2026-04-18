/**
 * Approval page — async Server Component that fetches payload from the
 * Deliberate server and renders the appropriate layout.
 *
 * Server-to-server fetch uses INTERNAL_API_URL (Docker network).
 * The interactive DecisionForm is a Client Component.
 *
 * See PRD §6.2: /a/{approval_id} — approver landing.
 */

import { DecisionForm } from "../../../components/decision-form";
import FinancialDecisionLayout from "../../../components/layouts/financial_decision";

// TODO(M2): Replace with signed token per PRD §6.6

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL || "http://localhost:4000";

interface ApprovalPayload {
  approval_id: string;
  status: string;
  layout: string;
  payload: Record<string, unknown>;
}

async function fetchApprovalPayload(
  approvalId: string
): Promise<ApprovalPayload | null> {
  try {
    const res = await fetch(
      `${INTERNAL_API_URL}/approvals/${approvalId}/payload`,
      { cache: "no-store" }
    );
    if (!res.ok) return null;
    return (await res.json()) as ApprovalPayload;
  } catch {
    return null;
  }
}

export default async function ApprovalPage({
  params,
}: {
  params: Promise<{ approval_id: string }>;
}) {
  const { approval_id } = await params;
  const data = await fetchApprovalPayload(approval_id);

  if (!data) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center p-8">
        <h1 className="text-2xl font-bold mb-4 text-red-600">
          Approval Not Found
        </h1>
        <p className="text-gray-600">
          This approval link may be invalid or expired.
        </p>
      </main>
    );
  }

  if (data.status === "decided") {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center p-8">
        <div className="max-w-lg w-full bg-green-50 border border-green-200 rounded-lg p-8 text-center">
          <div className="text-4xl mb-4">&#10003;</div>
          <h1 className="text-2xl font-bold mb-2 text-green-800">
            Decision Submitted
          </h1>
          <p className="text-green-700">
            This approval has already been decided. You can close this window.
          </p>
        </div>
      </main>
    );
  }

  const layoutPayload = data.payload as Record<string, unknown>;

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-3xl mx-auto py-8 px-4">
        <header className="mb-6">
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
            <span className="inline-block w-2 h-2 bg-amber-400 rounded-full" />
            Pending approval
          </div>
          <h1 className="text-2xl font-bold text-gray-900">
            {(layoutPayload.subject as string) || "Approval Request"}
          </h1>
        </header>

        {data.layout === "financial_decision" ? (
          <FinancialDecisionLayout payload={layoutPayload as any} />
        ) : (
          <div className="bg-white rounded-lg border p-6">
            <p className="text-gray-500">
              Layout &ldquo;{data.layout}&rdquo; is not yet implemented.
            </p>
            <pre className="mt-4 text-xs bg-gray-50 p-4 rounded overflow-auto">
              {JSON.stringify(layoutPayload, null, 2)}
            </pre>
          </div>
        )}

        <DecisionForm
          approvalId={approval_id}
          decisionOptions={
            (layoutPayload.decision_options as any[]) || [
              { type: "approve", label: "Approve" },
              { type: "modify", label: "Approve with change" },
              { type: "escalate", label: "Request more info" },
              { type: "reject", label: "Reject" },
            ]
          }
          rationaleCategories={
            (layoutPayload.rationale_categories as string[]) || [
              "product_issue",
              "retention",
              "policy_exception",
              "other",
            ]
          }
        />
      </div>
    </main>
  );
}
