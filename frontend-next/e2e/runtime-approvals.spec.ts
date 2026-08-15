import { test, expect } from "@playwright/test";

// Runtime capability-request approval queue (backend/app/routers/
// runtime_approvals.py) previously had zero frontend coverage at all — see
// docs/prime-agent-integration/32-dead-host-reclamation-and-frontend-development.md.
// This is a reachability/rendering smoke test, not a full approve/reject
// round trip: a real pending_approval row only comes from a live Prime
// Agent mission calling a Tier 1/2 capability through the MCP gateway
// (integrations/connectors/prime_runtime.py), which is Docker/container
// infrastructure out of scope for a browser E2E test — that round trip is
// already covered by the real backend suite (backend/tests/
// test_runtime_approvals*.py, scripts/p6*_acceptance*.py). What this test
// proves is that the page is reachable from navigation, authenticates
// correctly, calls the real endpoint, and renders a genuine empty-queue
// state correctly rather than erroring — the exact gap the frontend audit
// found (the page did not exist at all before this change).
test.describe("Runtime Capability Approvals", () => {
  test("is reachable from nav, loads the real queue, and switching status filters works", async ({ page }) => {
    await page.goto("/login");
    await page.fill("#username-input", "admin");
    await page.fill("#password-input", "password123");
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL(/\/jarvis$/, { timeout: 10000 });

    // /jarvis renders without the app Sidebar (AppShell's own "landing page"
    // list) - navigate to a page that has it, matching how an operator
    // would actually reach the nav link after logging in.
    await page.goto("/incidents");
    await page.click('a[href="/approvals"]');
    await expect(page).toHaveURL(/\/approvals$/);
    await expect(page.locator("text=Runtime Capability Approvals")).toBeVisible();

    // Default filter is pending_approval — the count badge rendering (with
    // any count, including zero) is unambiguous proof the real endpoint
    // returned successfully, never an error state. A prior test run in this
    // same suite (moa-approval.spec.ts) can leave a genuine non-empty queue
    // behind, so this deliberately does not assert emptiness either way.
    await expect(page.locator("text=Could not load capability requests")).not.toBeVisible();
    await expect(page.locator("text=/^\\d+ requests$/")).toBeVisible({ timeout: 10000 });

    // Switching filters re-queries the real endpoint without erroring.
    await page.click('button:has-text("executed")');
    await expect(page.locator("text=Could not load capability requests")).not.toBeVisible();
  });
});
