/**
 * Data access layout — for database, API, filesystem, or cloud storage access requests.
 * See PRD §4.2 for the layout specification.
 */

import { MarkdownText } from "../../markdown-text";
import {
  AgentReasoningSection,
  type AgentReasoning,
} from "../shared/agent-reasoning";

export interface DataAccessPayload {
  subject: string;
  resource_type: string; // "database", "api", "filesystem", "cloud_storage"
  resource_name: string;
  access_scope: string; // "read", "write", "admin"
  requester: string;
  requester_role?: string;
  risk_level?: "low" | "medium" | "high" | "critical";
  justification?: string;
  duration?: string; // "1h", "24h", "permanent"
  agent_reasoning: AgentReasoning;
  evidence?: Array<{ type: string; id: string; summary: string; url?: string }>;
  decision_options?: Array<{ type: string; label: string }>;
  rationale_categories?: string[];
}

const resourceTypeIcons: Record<string, string> = {
  database: "DB",
  api: "API",
  filesystem: "FS",
  cloud_storage: "S3",
};

const accessScopeColors: Record<string, string> = {
  read: "bg-blue-100 text-blue-800",
  write: "bg-amber-100 text-amber-800",
  admin: "bg-red-100 text-red-800",
};

const riskLevelColors: Record<string, string> = {
  low: "bg-green-100 text-green-800",
  medium: "bg-amber-100 text-amber-800",
  high: "bg-orange-100 text-orange-800",
  critical: "bg-red-100 text-red-800",
};

export default function DataAccessLayout({
  payload,
}: {
  payload: DataAccessPayload;
}) {
  return (
    <div className="space-y-4">
      {/* Resource card */}
      <div className="bg-white rounded-lg border p-6">
        <h3 className="text-sm font-medium text-gray-500 mb-3">
          Resource Access Request
        </h3>
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 bg-gray-100 rounded-lg flex items-center justify-center text-gray-600 font-bold text-xs flex-shrink-0">
            {resourceTypeIcons[payload.resource_type] ?? "RES"}
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-gray-900 text-lg truncate">
              {payload.resource_name}
            </div>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <span className="text-sm text-gray-500 capitalize">
                {payload.resource_type.replace("_", " ")}
              </span>
              <span
                className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${accessScopeColors[payload.access_scope] ?? "bg-gray-100 text-gray-600"}`}
              >
                {payload.access_scope} access
              </span>
              {payload.risk_level && (
                <span
                  className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${riskLevelColors[payload.risk_level] ?? "bg-gray-100 text-gray-600"}`}
                >
                  {payload.risk_level} risk
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Requester info */}
      <div className="bg-white rounded-lg border p-6">
        <h3 className="text-sm font-medium text-gray-500 mb-3">Requester</h3>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center text-blue-700 font-semibold text-sm flex-shrink-0">
            {payload.requester
              .split(" ")
              .map((n) => n[0])
              .join("")
              .slice(0, 2)
              .toUpperCase()}
          </div>
          <div>
            <div className="font-medium text-gray-900">{payload.requester}</div>
            {payload.requester_role && (
              <div className="text-sm text-gray-500">{payload.requester_role}</div>
            )}
          </div>
        </div>

        {/* Duration + Justification */}
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {payload.duration && (
            <div className="bg-gray-50 rounded p-3">
              <div className="text-xs font-medium text-gray-500 mb-0.5">
                Duration
              </div>
              <div className="text-sm text-gray-900">{payload.duration}</div>
            </div>
          )}
          {payload.justification && (
            <div className="bg-gray-50 rounded p-3 sm:col-span-2">
              <div className="text-xs font-medium text-gray-500 mb-0.5">
                Justification
              </div>
              <div className="text-sm text-gray-900">
                {payload.justification}
              </div>
            </div>
          )}
        </div>
      </div>

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
