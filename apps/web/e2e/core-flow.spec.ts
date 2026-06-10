import { expect, test } from "@playwright/test";
import path from "node:path";

import { seedUserAndSessionCookie } from "./utils/session";

const FIXTURE_PDF = path.resolve(
  __dirname,
  "../../api/tests/fixtures/sample-lab-result.pdf",
);

test("unauthenticated dashboard redirects to signin", async ({ page }) => {
  await page.goto("/es/dashboard");
  await expect(page).toHaveURL(/\/es\/signin/);
});

test("locale switcher: /en dashboard renders English", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(
    `e2e-locale-${Date.now()}@adelia.test`,
  );
  const context = await browser.newContext();
  await context.addCookies([cookie]);
  const page = await context.newPage();

  await page.goto("/en/dashboard");
  await expect(page.getByRole("heading", { name: "My documents" })).toBeVisible();

  await page.goto("/fr/dashboard");
  await expect(page.getByRole("heading", { name: "Mes documents" })).toBeVisible();
  await context.close();
});

test("upload → auto-poll to ready → detail shows OCR text", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(
    `e2e-upload-${Date.now()}@adelia.test`,
  );
  const context = await browser.newContext();
  await context.addCookies([cookie]);
  const page = await context.newPage();

  await page.goto("/es/dashboard/upload");
  await page.setInputFiles('input[type="file"]', FIXTURE_PDF);

  // Upload redirects to the dashboard; the new card links to the detail page.
  await page.waitForURL(/\/es\/dashboard$/, { timeout: 30_000 });
  await page.locator('a[href*="/dashboard/documents/"]').first().click();

  // Auto-poll flips the badge to Listo without manual reload.
  await expect(page.getByText("Listo")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("pre")).toContainText(/glucose/i, {
    timeout: 10_000,
  });
  await context.close();
});
