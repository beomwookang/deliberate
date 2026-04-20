"use client";

/**
 * DecisionForm — Client Component for submitting approval decisions.
 *
 * Measures review_duration_ms from page load to submission.
 * POSTs to NEXT_PUBLIC_API_URL/approvals/{id}/decide via browser fetch.
 */

import { useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:4000";

interface DecisionOption {
  type: string;
  label: string;
  fields?: string[];
}

interface DecisionFormProps {
  approvalId: string;
  decisionOptions: DecisionOption[];
  rationaleCategories: string[];
}

type SubmitState = "idle" | "submitting" | "success" | "already_decided" | "error";

const CATEGORY_LABELS: Record<string, string> = {
  product_issue: "Product Issue",
  retention: "Retention",
  policy_exception: "Policy Exception",
  other: "Other",
};

export function DecisionForm({
  approvalId,
  decisionOptions,
  rationaleCategories,
}: DecisionFormProps) {
  const loadTime = useRef(Date.now());
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [errorMessage, setErrorMessage] = useState("");

  // Reset load time on mount
  useEffect(() => {
    loadTime.current = Date.now();
  }, []);

  const handleSubmit = async () => {
    if (!selectedType) return;

    setSubmitState("submitting");
    setErrorMessage("");

    const reviewDurationMs = Date.now() - loadTime.current;

    try {
      const res = await fetch(`${API_URL}/approvals/${approvalId}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          decision_type: selectedType,
          decision_payload: null,
          rationale_category: selectedCategory,
          rationale_notes: notes || null,
          approver_email: "anonymous@deliberate.dev",
          review_duration_ms: reviewDurationMs,
          decided_via: "web_ui",
        }),
      });

      if (res.status === 409) {
        setSubmitState("already_decided");
        return;
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Server error ${res.status}`);
      }

      setSubmitState("success");
    } catch (err) {
      setSubmitState("error");
      setErrorMessage(
        err instanceof Error ? err.message : "Failed to submit decision"
      );
    }
  };

  if (submitState === "success") {
    return (
      <div className="mt-6 bg-green-50 border border-green-200 rounded-lg p-8 text-center">
        <div className="text-4xl mb-4">&#10003;</div>
        <h2 className="text-xl font-bold text-green-800 mb-2">
          Decision Submitted
        </h2>
        <p className="text-green-700">You can close this window.</p>
      </div>
    );
  }

  if (submitState === "already_decided") {
    return (
      <div className="mt-6 bg-amber-50 border border-amber-200 rounded-lg p-8 text-center">
        <div className="text-4xl mb-4">&#9888;</div>
        <h2 className="text-xl font-bold text-amber-800 mb-2">
          Already Decided
        </h2>
        <p className="text-amber-700">
          This approval has already been decided by another reviewer.
          Your submission was not recorded.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-6 bg-white rounded-lg border p-6">
      <h3 className="text-sm font-medium text-gray-500 mb-4">Your Decision</h3>

      {/* Decision buttons */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        {decisionOptions.map((opt) => {
          const isSelected = selectedType === opt.type;
          const colorMap: Record<string, string> = {
            approve:
              "border-green-300 bg-green-50 text-green-800 ring-green-500",
            modify:
              "border-blue-300 bg-blue-50 text-blue-800 ring-blue-500",
            escalate:
              "border-amber-300 bg-amber-50 text-amber-800 ring-amber-500",
            reject: "border-red-300 bg-red-50 text-red-800 ring-red-500",
          };
          const colors =
            colorMap[opt.type] ||
            "border-gray-300 bg-gray-50 text-gray-800 ring-gray-500";

          return (
            <button
              key={opt.type}
              onClick={() => setSelectedType(opt.type)}
              className={`
                px-4 py-3 rounded-lg border-2 text-sm font-medium transition-all
                ${isSelected ? `${colors} ring-2` : "border-gray-200 bg-white text-gray-700 hover:border-gray-300"}
              `}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      {/* Rationale chips */}
      {selectedType && (
        <>
          <h4 className="text-sm font-medium text-gray-500 mb-2">Reason</h4>
          <div className="flex flex-wrap gap-2 mb-4">
            {rationaleCategories.map((cat) => {
              const isSelected = selectedCategory === cat;
              return (
                <button
                  key={cat}
                  onClick={() =>
                    setSelectedCategory(isSelected ? null : cat)
                  }
                  className={`
                    px-3 py-1.5 rounded-full text-sm transition-all
                    ${isSelected ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"}
                  `}
                >
                  {CATEGORY_LABELS[cat] || cat}
                </button>
              );
            })}
          </div>

          {/* Notes textarea */}
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Additional notes (optional)"
            rows={3}
            className="w-full border rounded-lg px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent mb-4"
          />

          {/* Error message */}
          {submitState === "error" && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {errorMessage}
            </div>
          )}

          {/* Submit button */}
          <button
            onClick={handleSubmit}
            disabled={submitState === "submitting"}
            className="w-full py-3 bg-gray-900 text-white rounded-lg font-medium text-sm hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitState === "submitting" ? "Submitting..." : "Submit Decision"}
          </button>
        </>
      )}
    </div>
  );
}
