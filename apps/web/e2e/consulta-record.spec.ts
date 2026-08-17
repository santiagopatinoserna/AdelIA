import { expect, test } from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";

test.describe("consulta recorder", () => {
  test.beforeEach(async ({ page, context }) => {
    const { cookie } = await seedUserAndSessionCookie(
      `e2e-consulta-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
    );
    await context.addCookies([cookie]);
    await page.goto("/es/dashboard/consulta/grabar");
  });

  test("gate blocks recording until informed checkbox", async ({ page }) => {
    const start = page.getByRole("button", { name: "Grabar" });
    await expect(start).toBeDisabled();
    await page.getByRole("checkbox").check();
    await expect(start).toBeEnabled();
  });

  test("kill switch discards audio and logs declined event", async ({ page }) => {
    let uploaded = false;
    let declined = false;
    await page.route("**/api/backend/documents", (route) => {
      uploaded = true;
      return route.fulfill({ status: 500 });
    });
    await page.route("**/api/backend/consent-events", (route) => {
      declined = true;
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "x", created_at: "now" }),
      });
    });
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Grabar" }).click();
    await expect(page.getByRole("status")).toContainText("Grabando");
    await page.getByRole("button", { name: "El profesional se opone" }).click();
    await expect(page.getByText("Grabación descartada", { exact: false })).toBeVisible();
    expect(declined).toBe(true);
    expect(uploaded).toBe(false);
  });

  // NOTE: depends on Chromium's fake audio device actually feeding
  // MediaRecorder.ondataavailable in headless mode. If this flakes in CI,
  // per the Task 10 controller ruling this is the one test allowed to become
  // test.fixme() with a comment — gate + kill-switch + professionals are the
  // hard requirement, not this one.
  test("record → stop uploads source=consulta with consent version", async ({ page }) => {
    const form: Record<string, string> = {};
    await page.route("**/api/backend/documents", async (route) => {
      const req = route.request();
      const body = req.postDataBuffer()?.toString("latin1") ?? "";
      for (const field of ["source", "consent_policy_version", "locale"]) {
        const m = body.match(new RegExp(`name="${field}"\\r\\n\\r\\n([^\\r]+)`));
        if (m) form[field] = m[1];
      }
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-000000000001", status: "processing" }),
      });
    });
    await page.route("**/api/backend/documents/*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-000000000001", status: "ready" }),
      }),
    );
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Grabar" }).click();
    await page.waitForTimeout(1500); // capture some fake-device audio
    await page.getByRole("button", { name: "Terminar y guardar" }).click();
    await expect(page.getByText("Consulta guardada", { exact: false })).toBeVisible({ timeout: 15_000 });
    expect(form.source).toBe("consulta");
    expect(form.consent_policy_version).toBe("2026-08-17");
  });
});

test("professionals page is public in 3 locales", async ({ page }) => {
  for (const locale of ["es", "en", "fr"]) {
    await page.goto(`/${locale}/profesionales`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(page.url()).not.toContain("signin");
  }
});
