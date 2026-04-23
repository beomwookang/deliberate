/**
 * Global setup for Playwright tests.
 * Ensures the test API key hash is set in the database.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:4000";
const API_KEY = process.env.DELIBERATE_API_KEY || "test-api-key";

async function globalSetup() {
  // Verify server is reachable
  const healthRes = await fetch(`${API_URL}/health`);
  if (!healthRes.ok) {
    throw new Error(`Server not reachable at ${API_URL}. Run: docker compose up -d`);
  }

  // Try creating a test interrupt to verify API key works
  const testRes = await fetch(`${API_URL}/interrupts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Deliberate-API-Key": API_KEY,
    },
    body: JSON.stringify({
      thread_id: "playwright-setup-check",
      payload: { layout: "financial_decision", subject: "Setup check" },
    }),
  });

  if (testRes.status === 401) {
    throw new Error(
      `API key rejected (401). Update the applications table:\n` +
      `  python3 -c "import hashlib; print(hashlib.sha256('${API_KEY}'.encode()).hexdigest())" | ` +
      `xargs -I{} docker exec deliberate-postgres-1 psql -U deliberate -c ` +
      `"UPDATE applications SET api_key_hash = '{}' WHERE id = 'default';"`
    );
  }

  if (!testRes.ok) {
    throw new Error(`Setup check failed: ${testRes.status} ${await testRes.text()}`);
  }
}

export default globalSetup;
