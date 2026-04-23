/**
 * DecisionOverlay — shows the recorded decision for a decided approval.
 * Replaces DecisionForm for non-pending approvals.
 */

interface DecisionRecord {
  decision_type: string;
  approver_email: string;
  decided_at: string;
  rationale_category: string | null;
  rationale_notes: string | null;
  review_duration_ms: number | null;
  decision_payload: Record<string, unknown> | null;
}

interface DecisionOverlayProps {
  decision: DecisionRecord;
  status: string;
}

const DECISION_COLORS: Record<string, string> = {
  approve: "bg-green-100 text-green-800 border-green-200",
  modify: "bg-blue-100 text-blue-800 border-blue-200",
  reject: "bg-red-100 text-red-800 border-red-200",
  escalate: "bg-amber-100 text-amber-800 border-amber-200",
  timeout: "bg-gray-100 text-gray-800 border-gray-200",
  auto_approve: "bg-green-100 text-green-800 border-green-200",
};

function formatDuration(ms: number | null): string {
  if (ms === null || ms === 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}min`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function DecisionOverlay({ decision, status }: DecisionOverlayProps) {
  const colorClass =
    DECISION_COLORS[decision.decision_type] ||
    "bg-gray-100 text-gray-800 border-gray-200";

  return (
    <div className="mt-6 bg-white rounded-lg border p-6">
      <div className="flex items-center gap-3 mb-4">
        <h3 className="text-sm font-medium text-gray-500">Decision Record</h3>
        <span
          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${colorClass}`}
        >
          {decision.decision_type.replace("_", " ")}
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
        <div>
          <dt className="text-gray-500">Approver</dt>
          <dd className="text-gray-900 font-medium">{decision.approver_email}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Decided at</dt>
          <dd className="text-gray-900">{formatDate(decision.decided_at)}</dd>
        </div>
        {decision.rationale_category && (
          <div>
            <dt className="text-gray-500">Rationale</dt>
            <dd className="text-gray-900">{decision.rationale_category.replace("_", " ")}</dd>
          </div>
        )}
        <div>
          <dt className="text-gray-500">Review duration</dt>
          <dd className="text-gray-900">{formatDuration(decision.review_duration_ms)}</dd>
        </div>
      </dl>

      {decision.rationale_notes && (
        <div className="mt-4 pt-4 border-t">
          <dt className="text-sm text-gray-500 mb-1">Notes</dt>
          <dd className="text-sm text-gray-700 whitespace-pre-wrap">
            {decision.rationale_notes}
          </dd>
        </div>
      )}

      {decision.decision_payload && Object.keys(decision.decision_payload).length > 0 && (
        <div className="mt-4 pt-4 border-t">
          <dt className="text-sm text-gray-500 mb-1">Modifications</dt>
          <pre className="text-xs bg-gray-50 p-3 rounded overflow-auto">
            {JSON.stringify(decision.decision_payload, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
