/**
 * Approval page — server component that renders the layout for a given approval token.
 *
 * In M1+, this will fetch approval data from the server API and render the
 * appropriate layout component. For now it's a placeholder.
 *
 * See PRD §6.2: /a/{approval_token} — approver landing, renders layout-specific component.
 */

export default async function ApprovalPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="text-2xl font-bold mb-4">Approval Request</h1>
      <p className="text-gray-600">
        Approval page for token: <code className="bg-gray-100 px-2 py-1 rounded">{token}</code>
      </p>
    </main>
  );
}
