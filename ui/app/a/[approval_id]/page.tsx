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
import { DecisionOverlay } from "../../../components/decision-overlay";
import CodeDeploymentLayout from "../../../components/layouts/code_deployment";
import ContentModerationLayout from "../../../components/layouts/content_moderation";
import DataAccessLayout from "../../../components/layouts/data_access";
import DocumentReviewLayout from "../../../components/layouts/document_review";
import FinancialDecisionLayout from "../../../components/layouts/financial_decision";
import ProcedureSignoffLayout from "../../../components/layouts/procedure_signoff";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL || "http://localhost:4000";

interface ApprovalPayload {
  approval_id: string;
  status: string;
  layout: string;
  payload: Record<string, unknown>;
  decision?: {
    decision_type: string;
    approver_email: string;
    decided_at: string;
    rationale_category: string | null;
    rationale_notes: string | null;
    review_duration_ms: number | null;
    decision_payload: Record<string, unknown> | null;
  };
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

  if (data.status === "decided" && data.decision) {
    const decidedPayload = data.payload as Record<string, unknown>;
    return (
      <main className="min-h-screen bg-gray-50">
        <div className="max-w-3xl mx-auto py-8 px-4">
          <header className="mb-6">
            <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
              <span className="inline-block w-2 h-2 bg-green-400 rounded-full" />
              Decided
            </div>
            <h1 className="text-2xl font-bold text-gray-900">
              {(decidedPayload.subject as string) || "Approval Request"}
            </h1>
          </header>

          {data.layout === "financial_decision" ? (
            <FinancialDecisionLayout payload={decidedPayload as any} />
          ) : data.layout === "document_review" ? (
            <DocumentReviewLayout payload={decidedPayload as any} />
          ) : data.layout === "procedure_signoff" ? (
            <ProcedureSignoffLayout payload={decidedPayload as any} />
          ) : data.layout === "data_access" ? (
            <DataAccessLayout payload={decidedPayload as any} />
          ) : data.layout === "content_moderation" ? (
            <ContentModerationLayout payload={decidedPayload as any} />
          ) : data.layout === "code_deployment" ? (
            <CodeDeploymentLayout payload={decidedPayload as any} />
          ) : (
            <div className="bg-white rounded-lg border p-6">
              <pre className="text-xs bg-gray-50 p-4 rounded overflow-auto">
                {JSON.stringify(decidedPayload, null, 2)}
              </pre>
            </div>
          )}

          <DecisionOverlay decision={data.decision} status={data.status} />
        </div>
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
        ) : data.layout === "document_review" ? (
          <DocumentReviewLayout payload={layoutPayload as any} />
        ) : data.layout === "procedure_signoff" ? (
          <ProcedureSignoffLayout payload={layoutPayload as any} />
        ) : data.layout === "data_access" ? (
          <DataAccessLayout payload={layoutPayload as any} />
        ) : data.layout === "content_moderation" ? (
          <ContentModerationLayout payload={layoutPayload as any} />
        ) : data.layout === "code_deployment" ? (
          <CodeDeploymentLayout payload={layoutPayload as any} />
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
            (layoutPayload.decision_options as any[]) ||
            (data.layout === "document_review"
              ? [
                  { type: "approve", label: "Approve" },
                  { type: "modify", label: "Redline" },
                  { type: "reject", label: "Reject" },
                ]
              : data.layout === "procedure_signoff"
                ? [
                    { type: "approve", label: "Sign Off" },
                    { type: "modify", label: "Request Rework" },
                    { type: "escalate", label: "Escalate" },
                  ]
                : data.layout === "data_access"
                  ? [
                      { type: "approve", label: "Grant Access" },
                      { type: "modify", label: "Grant Limited" },
                      { type: "reject", label: "Deny" },
                    ]
                  : data.layout === "content_moderation"
                    ? [
                        { type: "approve", label: "Allow" },
                        { type: "reject", label: "Remove" },
                        { type: "modify", label: "Restrict" },
                        { type: "escalate", label: "Escalate" },
                      ]
                    : data.layout === "code_deployment"
                      ? [
                          { type: "approve", label: "Deploy" },
                          { type: "modify", label: "Deploy with Rollback" },
                          { type: "reject", label: "Reject" },
                        ]
                      : [
                          { type: "approve", label: "Approve" },
                          { type: "modify", label: "Approve with change" },
                          { type: "escalate", label: "Request more info" },
                          { type: "reject", label: "Reject" },
                        ])
          }
          rationaleCategories={
            (layoutPayload.rationale_categories as string[]) ||
            (data.layout === "document_review"
              ? ["clause_issue", "compliance_risk", "needs_revision", "other"]
              : data.layout === "procedure_signoff"
                ? [
                    "incomplete_step",
                    "exception_found",
                    "standards_violation",
                    "other",
                  ]
                : data.layout === "data_access"
                  ? [
                      "authorized_access",
                      "excessive_scope",
                      "insufficient_justification",
                      "other",
                    ]
                  : data.layout === "content_moderation"
                    ? [
                        "policy_violation",
                        "false_positive",
                        "context_dependent",
                        "other",
                      ]
                    : data.layout === "code_deployment"
                      ? [
                          "test_failure",
                          "breaking_change",
                          "insufficient_testing",
                          "other",
                        ]
                      : ["product_issue", "retention", "policy_exception", "other"])
          }
        />
      </div>
    </main>
  );
}
