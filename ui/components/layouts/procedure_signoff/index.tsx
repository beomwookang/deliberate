/**
 * Procedure signoff layout — for audit procedures, compliance checks, quality gates.
 * See PRD §4.2 for the layout specification.
 *
 * Placeholder — real implementation ships in M2.
 */

export interface ProcedureSignoffPayload {
  subject: string;
  checklist?: Array<{ step: string; status: string; notes?: string }>;
  exceptions?: Array<{ description: string; evidence_ref?: string; severity?: string }>;
  standards_reference?: string;
  agent_reasoning?: string;
  evidence?: Array<{ type: string; id?: string; summary: string; url?: string | null }>;
  decision_options?: Array<{ type: string; label: string; fields?: string[] }>;
  rationale_categories?: string[];
}

export default function ProcedureSignoffLayout({
  payload,
}: {
  payload: ProcedureSignoffPayload;
}) {
  return (
    <div className="p-8">
      <p className="text-gray-500">Layout: procedure_signoff</p>
      <h2 className="text-xl font-bold mt-2">{payload.subject}</h2>
    </div>
  );
}
