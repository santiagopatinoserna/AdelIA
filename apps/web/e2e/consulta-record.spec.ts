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

  // Two taps: the first only arms the link (label changes, nothing is
  // discarded), the second discards and logs the declined event.
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
    const confirm = page.getByRole("button", { name: "Toca otra vez para descartar la grabación" });
    await expect(confirm).toBeVisible();
    await expect(page.getByRole("status")).toContainText("Grabando");
    expect(declined).toBe(false);
    await confirm.click();
    await expect(page.getByText("Grabación descartada", { exact: false })).toBeVisible();
    await expect.poll(() => declined).toBe(true);
    expect(uploaded).toBe(false);
  });

  test("kill switch: one tap left alone disarms itself and keeps recording", async ({ page }) => {
    let declined = false;
    await page.route("**/api/backend/consent-events", (route) => {
      declined = true;
      return route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
    });
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Grabar" }).click();
    await expect(page.getByRole("status")).toContainText("Grabando");
    const stop = page.getByRole("button", { name: "Terminar y guardar" });
    const decline = page.getByRole("button", { name: "El profesional se opone" });
    // Not next to Stop any more: at least 24px below it.
    const stopBox = await stop.boundingBox();
    const declineBox = await decline.boundingBox();
    expect(declineBox!.y - (stopBox!.y + stopBox!.height)).toBeGreaterThanOrEqual(24);
    expect(declineBox!.height).toBeGreaterThanOrEqual(44);
    await decline.click();
    await expect(page.getByRole("button", { name: "Toca otra vez para descartar la grabación" })).toBeVisible();
    await page.waitForTimeout(4500);
    await expect(decline).toBeVisible();
    await expect(page.getByRole("status")).toContainText("Grabando");
    expect(declined).toBe(false);
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

  // Phone shell: the bottom tab bar only exists below md.
  test.describe("navigation lock (390x844)", () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test("a tab tap while recording asks first; 'Seguir grabando' keeps the mic open, 'Terminar y guardar' uploads", async ({ page }) => {
      let uploads = 0;
      await page.route("**/api/backend/documents", (route) => {
        uploads += 1;
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ id: "00000000-0000-0000-0000-000000000002", status: "processing" }),
        });
      });
      await page.route("**/api/backend/documents/*", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ id: "00000000-0000-0000-0000-000000000002", status: "ready" }),
        }),
      );
      const recorderUrl = /\/es\/dashboard\/consulta\/grabar$/;
      const tabBar = page.getByRole("navigation", { name: "Inicio" });
      const historyTab = tabBar.getByRole("link", { name: "Historial" });
      const dialog = page.getByRole("dialog");

      await page.getByRole("checkbox").check();
      await page.getByRole("button", { name: "Grabar" }).click();
      await expect(page.getByRole("status")).toContainText("Grabando");
      // The shell is marked as locked (tab bar and header dimmed, beforeunload armed).
      await expect(page.locator("html")).toHaveAttribute("data-recording", "");
      await expect(tabBar).toHaveAttribute("data-locked", "");

      // Tab bar: the URL does not change, the question comes up instead.
      await historyTab.click();
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("heading", { name: "¿Terminar la grabación?" })).toBeVisible();
      await expect(page).toHaveURL(recorderUrl);
      expect(uploads).toBe(0);

      await dialog.getByRole("button", { name: "Seguir grabando" }).click();
      await expect(dialog).toBeHidden();
      await expect(page.getByRole("status")).toContainText("Grabando");
      await expect(page).toHaveURL(recorderUrl);

      // Header link ("Subir", icon-only on a phone) and Escape: same guard, same outcome.
      await page.getByRole("link", { name: "Subir archivo" }).click();
      await expect(dialog).toBeVisible();
      await expect(page).toHaveURL(recorderUrl);
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(page.getByRole("status")).toContainText("Grabando");

      // Browser Back: intercepted too, still on the recorder.
      await page.evaluate(() => window.history.back());
      await expect(dialog).toBeVisible();
      await expect(page).toHaveURL(recorderUrl);
      await dialog.getByRole("button", { name: "Seguir grabando" }).click();
      await expect(dialog).toBeHidden();

      // "Terminar y guardar" from the dialog = the Stop button: the audio is uploaded, not discarded.
      await historyTab.click();
      await dialog.getByRole("button", { name: "Terminar y guardar" }).click();
      await expect(page.getByText("Consulta guardada", { exact: false })).toBeVisible({ timeout: 15_000 });
      expect(uploads).toBe(1);
      await expect(page.locator("html")).not.toHaveAttribute("data-recording", "");

      // Saved: the tab bar navigates again.
      await historyTab.click();
      await expect(page).toHaveURL(/\/es\/dashboard\/overview$/);
    });

    // After a failed upload the audio exists only in memory: the lock stays,
    // a tab tap asks, "Reintentar" re-posts the same bytes, and "Descartar"
    // from the dialog is the deliberate way out.
    test("a failed upload keeps the lock: a tab tap asks, 'Reintentar' re-posts, 'Descartar' lifts it", async ({ page }) => {
      let uploads = 0;
      await page.route("**/api/backend/documents", (route) => {
        uploads += 1;
        return route.fulfill({ status: 500 });
      });
      const recorderUrl = /\/es\/dashboard\/consulta\/grabar$/;
      const historyTab = page.getByRole("navigation", { name: "Inicio" }).getByRole("link", { name: "Historial" });
      const dialog = page.getByRole("dialog");
      const failure = page.getByRole("alert").filter({ hasText: "No se pudo subir la grabación" });

      await page.getByRole("checkbox").check();
      await page.getByRole("button", { name: "Grabar" }).click();
      await expect(page.getByRole("status")).toContainText("Grabando");
      await page.waitForTimeout(1500);
      await page.getByRole("button", { name: "Terminar y guardar" }).click();
      await expect(failure).toBeVisible({ timeout: 15_000 });
      expect(uploads).toBe(1);
      await expect(page.locator("html")).toHaveAttribute("data-recording", "");

      await historyTab.click();
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("heading", { name: "¿Salir sin guardar la consulta?" })).toBeVisible();
      await expect(page).toHaveURL(recorderUrl);

      await dialog.getByRole("button", { name: "Reintentar" }).click();
      await expect(dialog).toBeHidden();
      await expect.poll(() => uploads).toBe(2);
      await expect(failure).toBeVisible();
      await expect(page).toHaveURL(recorderUrl);
      await expect(page.locator("html")).toHaveAttribute("data-recording", "");

      await historyTab.click();
      await dialog.getByRole("button", { name: "Descartar la grabación" }).click();
      await expect(dialog).toBeHidden();
      await expect(page.getByRole("button", { name: "Grabar" })).toBeVisible();
      await expect(page.locator("html")).not.toHaveAttribute("data-recording", "");
      await historyTab.click();
      await expect(page).toHaveURL(/\/es\/dashboard\/overview$/);
    });
  });
});

test("professionals page is public in 3 locales", async ({ page }) => {
  for (const locale of ["es", "en", "fr"]) {
    await page.goto(`/${locale}/profesionales`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(page.url()).not.toContain("signin");
  }
});
