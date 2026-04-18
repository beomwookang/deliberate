/**
 * Financial decision layout — for refunds, expense approvals, budget requests.
 * See PRD §4.2 for the layout specification.
 *
 * Placeholder — real implementation ships in M1.
 */

export interface FinancialDecisionPayload {
  subject: string;
  amount?: { value: number; currency: string };
  customer?: { id: string; display_name: string; tenure?: string };
  agent_reasoning?: string;
  evidence?: Array<{ type: string; id?: string; summary: string; url?: string | null }>;
  decision_options?: Array<{ type: string; label: string; fields?: string[] }>;
  rationale_categories?: string[];
}

export default function FinancialDecisionLayout({
  payload,
}: {
  payload: FinancialDecisionPayload;
}) {
  return (
    <div className="p-8">
      <p className="text-gray-500">Layout: financial_decision</p>
      <h2 className="text-xl font-bold mt-2">{payload.subject}</h2>
    </div>
  );
}
