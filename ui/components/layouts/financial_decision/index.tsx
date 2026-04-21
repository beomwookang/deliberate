/**
 * Financial decision layout — for refunds, expense approvals, budget requests.
 * See PRD §4.2 for the layout specification.
 *
 * Supports both string and structured agent_reasoning (PRD §5.1 v3).
 */

import { MarkdownText } from "../../markdown-text";

type AgentReasoning =
  | string
  | {
      summary: string;
      points?: string[];
      confidence?: "high" | "medium" | "low";
    };

export interface FinancialDecisionPayload {
  subject: string;
  amount?: { value: number; currency: string };
  customer?: { id: string; display_name: string; tenure?: string };
  agent_reasoning?: AgentReasoning;
  evidence?: Array<{
    type: string;
    id?: string;
    summary: string;
    url?: string | null;
  }>;
  decision_options?: Array<{ type: string; label: string; fields?: string[] }>;
  rationale_categories?: string[];
}

function formatCurrency(value: number, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(value);
}

const confidenceColors: Record<string, string> = {
  high: "bg-green-100 text-green-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-orange-100 text-orange-800",
};

function AgentReasoningSection({
  reasoning,
}: {
  reasoning: AgentReasoning;
}) {
  // String form: render as markdown
  if (typeof reasoning === "string") {
    return <MarkdownText content={reasoning} className="text-gray-700" />;
  }

  // Structured form
  return (
    <div className="space-y-3">
      {/* Confidence badge */}
      {reasoning.confidence && (
        <span
          className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${confidenceColors[reasoning.confidence] || "bg-gray-100 text-gray-600"}`}
        >
          Confidence: {reasoning.confidence}
        </span>
      )}

      {/* Summary */}
      <p className="text-gray-900 font-medium text-sm">{reasoning.summary}</p>

      {/* Points as bullet list */}
      {reasoning.points && reasoning.points.length > 0 && (
        <ul className="list-disc list-inside space-y-1">
          {reasoning.points.map((point, i) => (
            <li key={i} className="text-gray-700 text-sm">
              <MarkdownText
                content={point}
                className="inline [&>p]:inline"
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function FinancialDecisionLayout({
  payload,
}: {
  payload: FinancialDecisionPayload;
}) {
  return (
    <div className="space-y-4">
      {/* Amount card */}
      {payload.amount && (
        <div className="bg-white rounded-lg border p-6">
          <div className="text-sm font-medium text-gray-500 mb-1">Amount</div>
          <div className="text-3xl font-bold text-gray-900">
            {formatCurrency(payload.amount.value, payload.amount.currency)}
          </div>
        </div>
      )}

      {/* Customer info */}
      {payload.customer && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-3">Customer</h3>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center text-blue-700 font-semibold">
              {payload.customer.display_name
                .split(" ")
                .map((n) => n[0])
                .join("")}
            </div>
            <div>
              <div className="font-medium text-gray-900">
                {payload.customer.display_name}
              </div>
              <div className="text-sm text-gray-500">
                {payload.customer.id}
                {payload.customer.tenure && ` · ${payload.customer.tenure}`}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Agent reasoning */}
      {payload.agent_reasoning && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-2">
            Agent Reasoning
          </h3>
          <AgentReasoningSection reasoning={payload.agent_reasoning} />
        </div>
      )}

      {/* Evidence table */}
      {payload.evidence && payload.evidence.length > 0 && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-3">Evidence</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 pr-4 font-medium text-gray-500">
                    Type
                  </th>
                  <th className="text-left py-2 pr-4 font-medium text-gray-500">
                    ID
                  </th>
                  <th className="text-left py-2 font-medium text-gray-500">
                    Summary
                  </th>
                </tr>
              </thead>
              <tbody>
                {payload.evidence.map((item, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-2 pr-4">
                      <span className="inline-block px-2 py-0.5 bg-gray-100 rounded text-xs font-medium text-gray-600">
                        {item.type}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-gray-600">
                      {item.url ? (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline"
                        >
                          {item.id || "-"}
                        </a>
                      ) : (
                        item.id || "-"
                      )}
                    </td>
                    <td className="py-2 text-gray-700">
                      <MarkdownText content={item.summary} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
