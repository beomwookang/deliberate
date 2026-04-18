/**
 * Document review layout — for contracts, policies, legal redlines.
 * See PRD §4.2 for the layout specification.
 *
 * Placeholder — real implementation ships in M2.
 */

export interface DocumentReviewPayload {
  subject: string;
  document_url?: string;
  flagged_clauses?: Array<{ clause: string; reason: string }>;
  agent_reasoning?: string;
  evidence?: Array<{ type: string; id?: string; summary: string; url?: string | null }>;
  decision_options?: Array<{ type: string; label: string; fields?: string[] }>;
  rationale_categories?: string[];
}

export default function DocumentReviewLayout({
  payload,
}: {
  payload: DocumentReviewPayload;
}) {
  return (
    <div className="p-8">
      <p className="text-gray-500">Layout: document_review</p>
      <h2 className="text-xl font-bold mt-2">{payload.subject}</h2>
    </div>
  );
}
