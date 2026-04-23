/**
 * Shared AgentReasoningSection component used by all layout types.
 * Renders both string and structured agent_reasoning (PRD §5.1 v3).
 */

import { MarkdownText } from "../../markdown-text";

export type AgentReasoning =
  | string
  | {
      summary: string;
      points?: string[];
      confidence?: "high" | "medium" | "low";
    };

const confidenceColors: Record<string, string> = {
  high: "bg-green-100 text-green-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-orange-100 text-orange-800",
};

export function AgentReasoningSection({
  reasoning,
}: {
  reasoning: AgentReasoning;
}) {
  if (typeof reasoning === "string") {
    return <MarkdownText content={reasoning} className="text-gray-700" />;
  }

  return (
    <div className="space-y-3">
      {reasoning.confidence && (
        <span
          className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${confidenceColors[reasoning.confidence] ?? "bg-gray-100 text-gray-600"}`}
        >
          Confidence: {reasoning.confidence}
        </span>
      )}
      <p className="text-gray-900 font-medium text-sm">{reasoning.summary}</p>
      {reasoning.points && reasoning.points.length > 0 && (
        <ul className="list-disc list-inside space-y-1">
          {reasoning.points.map((point, i) => (
            <li key={i} className="text-gray-700 text-sm">
              <MarkdownText content={point} className="inline [&>p]:inline" />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
