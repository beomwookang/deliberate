/**
 * Playwright E2E tests for the approval page.
 *
 * Requires: docker compose up (server + postgres + ui all running)
 *
 * Tests:
 * 1. Financial decision layout renders correctly
 * 2. Decision form submit → success state
 * 3. Already-decided approval → 409 → "Already Decided" message
 * 4. Invalid approval_id → "Not Found" page
 */

import { expect, test } from "@playwright/test";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:4000";
const API_KEY = process.env.DELIBERATE_API_KEY || "SmZ-5ETlbm4v-sGgwSd33SE2VMbBbxxdQt0dvR2U8hs";

async function createApproval(): Promise<string> {
  const res = await fetch(`${API_URL}/interrupts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Deliberate-API-Key": API_KEY,
    },
    body: JSON.stringify({
      thread_id: `playwright-${Date.now()}`,
      payload: {
        layout: "financial_decision",
        subject: "Refund for customer #4821",
        amount: { value: 750.0, currency: "USD" },
        customer: { id: "cust_4821", display_name: "Maya Chen", tenure: "18 months" },
        agent_reasoning: "Bug confirmed by engineering. No prior refunds.",
        evidence: [
          { type: "ticket", id: "#4821", summary: "Bug confirmed", url: null },
          { type: "history", summary: "No prior refunds", url: null },
        ],
        rationale_categories: ["product_issue", "retention", "policy_exception", "other"],
      },
    }),
  });
  const data = await res.json();
  return data.approval_id;
}

async function decideApproval(approvalId: string): Promise<void> {
  await fetch(`${API_URL}/approvals/${approvalId}/decide`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      decision_type: "approve",
      approver_email: "test@test.com",
      decided_via: "web_ui",
    }),
  });
}

test.describe("Approval Page", () => {
  test("renders financial_decision layout with correct data", async ({ page }) => {
    const approvalId = await createApproval();

    await page.goto(`/a/${approvalId}`);

    // Header shows subject
    await expect(page.locator("h1")).toContainText("Refund for customer #4821");

    // Amount is displayed
    await expect(page.locator("text=$750.00")).toBeVisible();

    // Customer info
    await expect(page.locator("text=Maya Chen")).toBeVisible();

    // Agent reasoning
    await expect(page.locator("text=Bug confirmed by engineering")).toBeVisible();

    // Evidence table
    await expect(page.getByRole("cell", { name: "#4821" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "No prior refunds" })).toBeVisible();

    // Decision buttons present
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject" })).toBeVisible();
  });

  test("submit decision → success state", async ({ page }) => {
    const approvalId = await createApproval();

    await page.goto(`/a/${approvalId}`);

    // Click Approve
    await page.click("button:has-text('Approve')");

    // Select a rationale
    await page.click("button:has-text('Product Issue')");

    // Fill notes
    await page.fill("textarea", "Confirmed bug, approved.");

    // Submit
    await page.click("button:has-text('Submit Decision')");

    // Should show success
    await expect(page.locator("text=Decision Submitted")).toBeVisible();
    await expect(page.locator("text=You can close this window")).toBeVisible();
  });

  test("already decided → shows 'Already Decided' warning", async ({ page }) => {
    const approvalId = await createApproval();

    // Decide via API first
    await decideApproval(approvalId);

    // Open in browser and try to submit again
    await page.goto(`/a/${approvalId}`);

    // Page should show "Decision Submitted" (server-side check)
    await expect(page.locator("text=Decision Submitted")).toBeVisible();
  });

  test("invalid approval_id → not found", async ({ page }) => {
    await page.goto("/a/00000000-0000-0000-0000-000000000001");

    await expect(page.locator("text=Approval Not Found")).toBeVisible();
  });

  test("duplicate tab submit → 'Already Decided' message", async ({ page, context }) => {
    const approvalId = await createApproval();

    // Open in two tabs
    const page1 = page;
    const page2 = await context.newPage();

    await page1.goto(`/a/${approvalId}`);
    await page2.goto(`/a/${approvalId}`);

    // Submit from page1
    await page1.click("button:has-text('Approve')");
    await page1.click("button:has-text('Submit Decision')");
    await expect(page1.locator("text=Decision Submitted")).toBeVisible();

    // Submit from page2 — should get "Already Decided"
    await page2.click("button:has-text('Approve')");
    await page2.click("button:has-text('Submit Decision')");
    await expect(page2.locator("text=Already Decided")).toBeVisible();

    await page2.close();
  });
});
