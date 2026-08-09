import { test, expect } from "@playwright/test";

test.describe("MOA Workflow E2E Smoke Test", () => {
  test("logs in and completes an MOA approval end-to-end", async ({ page }) => {
    // 1. Navigate to login page
    await page.goto("/login");
    await expect(page.locator("text=Sign in")).toBeVisible();

    // 2. Fill login form (admin / admin)
    await page.fill("#username-input", "admin");
    await page.fill("#password-input", "password123");
    await page.click('button[type="submit"]');


    // 3. Verify automatic redirection to /jarvis
    await expect(page).toHaveURL(/\/jarvis$/, { timeout: 10000 });


    // 4. Submit MOA Offboarding Task for Priya Raman
    await expect(page.locator("text=Execute MOA Intent")).toBeVisible();

    const employeeInput = page.locator('input[placeholder*="Marcus Vance"]');
    await employeeInput.fill("Priya Raman");

    const instructionInput = page.locator('input[placeholder*="Offboard"]');
    await instructionInput.fill("Priya Raman is leaving Friday, complete her offboarding");


    // 5. Click Execute MOA Intent
    await page.click('button:has-text("Execute MOA Intent")');

    // 6. Wait for proposed action pending approval card to render
    const approveBtn = page.locator('button:has-text("Approve & Resume Execution")');
    await expect(approveBtn).toBeVisible({ timeout: 15000 });

    // 7. Click Approve & Resume Execution
    await approveBtn.click();

    // 8. Assert successful execution completion (MOA Execution Status: OK)
    await expect(page.locator("text=MOA Execution Status:")).toBeVisible({ timeout: 15000 });
    await expect(page.locator('span:has-text("OK")').first()).toBeVisible({ timeout: 15000 });

  });
});
