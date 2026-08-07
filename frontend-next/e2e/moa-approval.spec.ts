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


    await page.waitForTimeout(2000);
    console.log("Current page URL after submit:", page.url());
    const errorText = await page.locator(".text-status-red").textContent().catch(() => null);
    if (errorText) console.log("Login error on page:", errorText);

    // 3. Verify automatic redirection to /jarvis
    await page.waitForURL("**/jarvis", { timeout: 10000 });
    await expect(page).toHaveURL(/\/jarvis$/);

    // 4. Submit MOA Offboarding Task for Priya Raman
    await expect(page.locator("text=Execute MOA Intent")).toBeVisible();

    const employeeInput = page.locator('input[placeholder*="Priya Raman"]');
    await employeeInput.fill("Priya Raman");

    const instructionInput = page.locator('textarea[placeholder*="offboarding"]');
    await instructionInput.fill("Priya Raman is leaving Friday, complete her offboarding");

    // 5. Click Execute MOA Intent
    await page.click('button:has-text("Execute MOA Intent")');

    // 6. Wait for proposed action pending approval card to render
    const approveBtn = page.locator('button:has-text("Approve & Resume Execution")');
    await expect(approveBtn).toBeVisible({ timeout: 15000 });

    // 7. Click Approve & Resume Execution
    await approveBtn.click();

    // 8. Assert successful execution completion (STATUS: OK or completed badge)
    await expect(page.locator("text=STATUS: OK")).toBeVisible({ timeout: 15000 });
  });
});
