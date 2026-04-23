/**
 * Content moderation layout — for flagged user content requiring human review.
 * See PRD §4.2 for the layout specification.
 */

import { MarkdownText } from "../../markdown-text";
import {
  AgentReasoningSection,
  type AgentReasoning,
} from "../shared/agent-reasoning";

export interface ContentModerationPayload {
  subject: string;
  content_type: string; // "text", "image", "video", "mixed"
  content_preview?: string;
  content_url?: string;
  flagged_items: Array<{
    category: string; // "hate_speech", "violence", "spam", "misinformation", etc.
    severity: "low" | "medium" | "high";
    description: string;
    evidence_ref?: string;
  }>;
  policy_references?: Array<{ name: string; url?: string; section?: string }>;
  agent_reasoning: AgentReasoning;
  evidence?: Array<{ type: string; id: string; summary: string; url?: string }>;
  decision_options?: Array<{ type: string; label: string }>;
  rationale_categories?: string[];
}

const severityColors: Record<string, string> = {
  low: "bg-yellow-100 text-yellow-800",
  medium: "bg-orange-100 text-orange-800",
  high: "bg-red-100 text-red-800",
};

const severityDotColors: Record<string, string> = {
  low: "bg-yellow-400",
  medium: "bg-orange-400",
  high: "bg-red-500",
};

export default function ContentModerationLayout({
  payload,
}: {
  payload: ContentModerationPayload;
}) {
  return (
    <div className="space-y-4">
      {/* Content preview card */}
      <div className="bg-white rounded-lg border p-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-gray-500">Content</h3>
          <span className="inline-block px-2 py-0.5 bg-gray-100 rounded text-xs font-medium text-gray-600 capitalize">
            {payload.content_type}
          </span>
        </div>
        {payload.content_preview && (
          <div className="bg-gray-50 rounded p-4 text-sm text-gray-800 border border-gray-200 whitespace-pre-wrap break-words">
            {payload.content_preview}
          </div>
        )}
        {payload.content_url && (
          <div className="mt-2">
            <a
              href={payload.content_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-blue-600 hover:underline"
            >
              View original content &rarr;
            </a>
          </div>
        )}
        {!payload.content_preview && !payload.content_url && (
          <p className="text-sm text-gray-400 italic">
            No preview available.
          </p>
        )}
      </div>

      {/* Flagged items */}
      {payload.flagged_items.length > 0 && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-3">
            Flagged Issues ({payload.flagged_items.length})
          </h3>
          <ul className="space-y-3">
            {payload.flagged_items.map((item, i) => (
              <li
                key={i}
                className="flex items-start gap-3 p-3 rounded-lg bg-gray-50 border border-gray-100"
              >
                <span
                  className={`inline-block w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${severityDotColors[item.severity] ?? "bg-gray-400"}`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="font-medium text-sm text-gray-900 capitalize">
                      {item.category.replace(/_/g, " ")}
                    </span>
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${severityColors[item.severity] ?? "bg-gray-100 text-gray-600"}`}
                    >
                      {item.severity}
                    </span>
                  </div>
                  <p className="text-sm text-gray-700">{item.description}</p>
                  {item.evidence_ref && (
                    <p className="text-xs text-gray-400 mt-1">
                      Ref: {item.evidence_ref}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Policy references */}
      {payload.policy_references && payload.policy_references.length > 0 && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-3">
            Policy References
          </h3>
          <ul className="space-y-2">
            {payload.policy_references.map((ref, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <span className="text-gray-400 mt-0.5">&#8212;</span>
                <div>
                  {ref.url ? (
                    <a
                      href={ref.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline font-medium"
                    >
                      {ref.name}
                    </a>
                  ) : (
                    <span className="font-medium text-gray-900">{ref.name}</span>
                  )}
                  {ref.section && (
                    <span className="text-gray-500 ml-1">§ {ref.section}</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Agent reasoning */}
      <div className="bg-gray-50 rounded-lg border border-gray-200 p-6">
        <h3 className="text-sm font-medium text-gray-500 mb-2">
          Agent Reasoning
        </h3>
        <AgentReasoningSection reasoning={payload.agent_reasoning} />
      </div>

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
