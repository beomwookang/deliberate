/**
 * Code deployment layout — for service deployment approvals.
 * See PRD §4.2 for the layout specification.
 */

import { MarkdownText } from "../../markdown-text";
import {
  AgentReasoningSection,
  type AgentReasoning,
} from "../shared/agent-reasoning";

export interface CodeDeploymentPayload {
  subject: string;
  environment: string; // "staging", "production", "canary"
  service_name: string;
  version?: string;
  diff_summary?: { files_changed: number; insertions: number; deletions: number };
  rollback_plan?: string;
  test_results?: { passed: number; failed: number; skipped: number };
  breaking_changes?: string[];
  agent_reasoning: AgentReasoning;
  evidence?: Array<{ type: string; id: string; summary: string; url?: string }>;
  decision_options?: Array<{ type: string; label: string }>;
  rationale_categories?: string[];
}

const environmentColors: Record<string, string> = {
  staging: "bg-blue-100 text-blue-800",
  production: "bg-red-100 text-red-800",
  canary: "bg-amber-100 text-amber-800",
};

export default function CodeDeploymentLayout({
  payload,
}: {
  payload: CodeDeploymentPayload;
}) {
  const testResults = payload.test_results;
  const totalTests = testResults
    ? testResults.passed + testResults.failed + testResults.skipped
    : 0;

  return (
    <div className="space-y-4">
      {/* Service + environment card */}
      <div className="bg-white rounded-lg border p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-medium text-gray-500 mb-1">Service</h3>
            <div className="text-xl font-bold text-gray-900">
              {payload.service_name}
            </div>
            {payload.version && (
              <div className="text-sm text-gray-500 mt-0.5">
                Version {payload.version}
              </div>
            )}
          </div>
          <span
            className={`inline-block px-3 py-1 rounded-full text-sm font-medium capitalize flex-shrink-0 ${environmentColors[payload.environment] ?? "bg-gray-100 text-gray-600"}`}
          >
            {payload.environment}
          </span>
        </div>
      </div>

      {/* Diff summary */}
      {payload.diff_summary && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-3">
            Change Summary
          </h3>
          <div className="flex items-center gap-6">
            <div className="text-center">
              <div className="text-2xl font-bold text-gray-900">
                {payload.diff_summary.files_changed}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">files changed</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-green-600">
                +{payload.diff_summary.insertions}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">insertions</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-red-600">
                -{payload.diff_summary.deletions}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">deletions</div>
            </div>
          </div>
        </div>
      )}

      {/* Test results */}
      {testResults && totalTests > 0 && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-3">
            Test Results
          </h3>
          {/* Progress bar */}
          <div className="flex h-3 rounded-full overflow-hidden mb-3 bg-gray-100">
            {testResults.passed > 0 && (
              <div
                className="bg-green-500 h-full"
                style={{
                  width: `${(testResults.passed / totalTests) * 100}%`,
                }}
              />
            )}
            {testResults.failed > 0 && (
              <div
                className="bg-red-500 h-full"
                style={{
                  width: `${(testResults.failed / totalTests) * 100}%`,
                }}
              />
            )}
            {testResults.skipped > 0 && (
              <div
                className="bg-gray-300 h-full"
                style={{
                  width: `${(testResults.skipped / totalTests) * 100}%`,
                }}
              />
            )}
          </div>
          <div className="flex items-center gap-4 text-sm">
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500" />
              <span className="text-gray-700">
                {testResults.passed} passed
              </span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-500" />
              <span className="text-gray-700">
                {testResults.failed} failed
              </span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-gray-300" />
              <span className="text-gray-700">
                {testResults.skipped} skipped
              </span>
            </span>
          </div>
        </div>
      )}

      {/* Breaking changes */}
      {payload.breaking_changes && payload.breaking_changes.length > 0 && (
        <div className="bg-orange-50 rounded-lg border border-orange-200 p-6">
          <h3 className="text-sm font-medium text-orange-700 mb-3 flex items-center gap-2">
            <span className="inline-block w-4 h-4 rounded-full bg-orange-500 text-white text-xs flex items-center justify-center font-bold leading-none">
              !
            </span>
            Breaking Changes ({payload.breaking_changes.length})
          </h3>
          <ul className="space-y-2">
            {payload.breaking_changes.map((change, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-orange-900">
                <span className="text-orange-400 mt-0.5 flex-shrink-0">&#9679;</span>
                {change}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Rollback plan */}
      {payload.rollback_plan && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-2">
            Rollback Plan
          </h3>
          <p className="text-sm text-gray-700">{payload.rollback_plan}</p>
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
