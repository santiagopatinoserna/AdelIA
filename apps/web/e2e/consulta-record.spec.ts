import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { Pool } from "pg";

import { isoMonthsAgo, seedProfile } from "./utils/seed";
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

  // QA 2026-11-12, 10/10: the "Grabar consulta" shortcut opens this page with
  // a full load, and a tick made before React hydrated left the box ticked
  // and "Grabar" disabled under it. The scripts are held until she has
  // ticked, so the tick is the native one React never saw.
  test("a tick made before the page is ready still enables 'Grabar'", async ({ page }) => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/_next/static/**/*.js", async (route) => {
      await held;
      await route.continue();
    });
    await page.goto("/es/dashboard/consulta/grabar", { waitUntil: "domcontentloaded" });
    const box = page.getByRole("checkbox");
    const start = page.getByRole("button", { name: "Grabar" });
    await box.check();
    await expect(start).toBeDisabled(); // nothing has hydrated yet
    release();
    await expect(start).toBeEnabled({ timeout: 60_000 });
    await expect(box).toBeChecked();
  });

  // Only a refusal is a permission problem. A busy or missing mic used to
  // say "no tiene permiso" and sent her to a setting that was already right.
  for (const [errorName, line] of [
    ["NotReadableError", "El micrófono está ocupado o no aparece"],
    ["NotFoundError", "El micrófono está ocupado o no aparece"],
    ["AbortError", "El micrófono está ocupado o no aparece"],
    ["NotAllowedError", "AdelIA no tiene permiso de micrófono"],
  ] as const) {
    test(`getUserMedia ${errorName} gets its own line`, async ({ page }) => {
      await page.addInitScript((name) => {
        navigator.mediaDevices.getUserMedia = () =>
          Promise.reject(new DOMException("stub", name));
      }, errorName);
      await page.reload();
      await page.getByRole("checkbox").check();
      await page.getByRole("button", { name: "Grabar" }).click();
      const alert = page.getByRole("alert").filter({ hasText: line });
      await expect(alert).toBeVisible();
      if (errorName !== "NotAllowedError") {
        await expect(alert).toContainText("vuelve a tocar Grabar");
        await expect(page.getByText("no tiene permiso", { exact: false })).toHaveCount(0);
      }
      // Still at the gate: she can tap again once the call is over.
      await expect(page.getByRole("button", { name: "Grabar" })).toBeEnabled();
    });
  }

  // An in-app browser (WhatsApp, Instagram) has no recording API at all. The
  // busy-mic line sent her to close apps that were not the problem.
  test("a browser that cannot record says so and names the way out", async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Navigator.prototype, "mediaDevices", {
        get: () => undefined,
        configurable: true,
      });
    });
    await page.reload();
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Grabar" }).click();
    const alert = page.getByRole("alert").filter({ hasText: "Este navegador no deja grabar" });
    await expect(alert).toHaveText(
      "Este navegador no deja grabar. Abre esta página en Chrome o Safari.",
    );
    await expect(page.getByText("ocupado", { exact: false })).toHaveCount(0);
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
      for (const field of ["source", "consent_policy_version", "locale", "interrupted"]) {
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
    // A visit she stopped herself is whole: no "interrupted" flag.
    expect(form.interrupted).toBeUndefined();
  });

  // Third QA wave 2026-11-13 (review of the summary package): a call that
  // takes the mic, a track that ends or an iOS interruption stops the
  // recorder without her tap. That recording ends wherever it was cut, so it
  // goes up flagged like a reload's and its last sentence is not summarised.
  test("a recording the browser stops by itself is uploaded as cut", async ({ page }) => {
    const form: Record<string, string> = {};
    await page.route("**/api/backend/documents", async (route) => {
      const body = route.request().postDataBuffer()?.toString("latin1") ?? "";
      for (const field of ["source", "interrupted"]) {
        const m = body.match(new RegExp(`name="${field}"\\r\\n\\r\\n([^\\r]+)`));
        if (m) form[field] = m[1];
      }
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-000000000004", status: "processing" }),
      });
    });
    await page.route("**/api/backend/documents/*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-000000000004", status: "ready" }),
      }),
    );
    // A handle on the recorder the page creates, to stop it as the browser would.
    await page.evaluate(() => {
      const real = MediaRecorder.prototype.start;
      MediaRecorder.prototype.start = function (this: MediaRecorder, timeslice?: number) {
        (window as unknown as { __rec?: MediaRecorder }).__rec = this;
        return real.call(this, timeslice);
      };
    });
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Grabar" }).click();
    await expect(page.getByRole("status")).toContainText("Grabando");
    await page.waitForTimeout(1500); // capture some fake-device audio
    const stopped = await page.evaluate(() => {
      const rec = (window as unknown as { __rec?: MediaRecorder }).__rec;
      rec?.stop();
      return Boolean(rec);
    });
    expect(stopped).toBe(true);
    await expect(page.getByText("Consulta guardada", { exact: false })).toBeVisible({ timeout: 15_000 });
    expect(form.source).toBe("consulta");
    expect(form.interrupted).toBe("true");
  });

  // QA 2026-11-12: after the visit nothing led back to the conversation. The
  // first, primary button now asks about it there (/dashboard?ask=, contract
  // C2), then the transcript, then the summary for the pediatrician.
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

// The recording is also kept on the device (lib/consulta-draft): a reload, a
// closed tab or a killed one lost the whole visit (QA 2026-11-12, 6/6).
test.describe("interrupted recording", () => {
  test.describe.configure({ timeout: 180_000 });

  async function draftCount(page: Page): Promise<number> {
    return page.evaluate(
      () =>
        new Promise<number>((resolve, reject) => {
          const req = indexedDB.open("adelia-consulta", 1);
          req.onupgradeneeded = () => req.result.createObjectStore("draft");
          req.onerror = () => reject(req.error);
          req.onsuccess = () => {
            const db = req.result;
            const count = db.transaction("draft").objectStore("draft").count();
            count.onsuccess = () => {
              db.close();
              resolve(count.result);
            };
          };
        }),
    );
  }

  // A draft as the recorder leaves it after a killed tab, written straight
  // into the device store: the tests below are about what the recorder does
  // with it, not about MediaRecorder, so they need no recording.
  async function seedDraft(
    page: Page,
    meta: { profileId: string; startedAt: number; policyVersion?: string },
  ) {
    await page.evaluate(
      (m) =>
        new Promise<void>((resolve, reject) => {
          const req = indexedDB.open("adelia-consulta", 1);
          req.onupgradeneeded = () => req.result.createObjectStore("draft");
          req.onerror = () => reject(req.error);
          req.onsuccess = () => {
            const db = req.result;
            const tx = db.transaction("draft", "readwrite");
            const store = tx.objectStore("draft");
            store.put({ mime: "audio/webm", ...m }, "meta");
            for (const [i, fill] of [7, 8].entries()) {
              const bytes = new Uint8Array(4096).fill(fill).buffer;
              store.put({ type: "audio/webm", bytes }, `chunk-00000${i}`);
            }
            tx.oncomplete = () => {
              db.close();
              resolve();
            };
            tx.onerror = () => reject(tx.error);
          };
        }),
      meta,
    );
  }

  async function seedAccount(page: Page, context: BrowserContext, children: string[]) {
    const { cookie, userId } = await seedUserAndSessionCookie(
      `e2e-consulta-draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
    );
    // The first child is the default one, the child the page starts on. An
    // account has one default (idx_profiles_one_default_per_user), so the
    // siblings go in here and not through seedProfile.
    const [first, ...siblings] = children;
    const ids = [await seedProfile(userId, { displayName: first, dateOfBirth: isoMonthsAgo(9) })];
    if (siblings.length) {
      const db = new Pool({
        host: process.env.POSTGRES_HOST ?? "localhost",
        port: Number(process.env.POSTGRES_PORT ?? "5434"),
        user: process.env.POSTGRES_USER ?? "adelia",
        password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
        database: process.env.POSTGRES_DB ?? "adelia",
      });
      for (const name of siblings) {
        const { rows } = await db.query(
          `INSERT INTO profiles (user_id, display_name, relationship, date_of_birth, is_default)
           VALUES ($1, $2, 'child', $3::date, false) RETURNING id`,
          [userId, name, isoMonthsAgo(30)],
        );
        ids.push(rows[0].id as string);
      }
      await db.end();
    }
    await context.addCookies([cookie]);
    await page.goto("/es/dashboard/consulta/grabar");
    await expect(page.getByRole("button", { name: "Grabar", exact: true })).toBeVisible();
    return ids;
  }

  // Holds every indexedDB.open until the test calls window.__releaseDraftCheck
  // (or for good): the device check that runs when the recorder opens.
  function holdDeviceCheck() {
    const realOpen = IDBFactory.prototype.open;
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    (window as unknown as { __releaseDraftCheck: () => void }).__releaseDraftCheck = release;
    IDBFactory.prototype.open = function (this: IDBFactory, name: string, version?: number) {
      const fake = {} as Record<string, unknown>;
      void held.then(() => {
        const real = realOpen.call(this, name, version);
        Object.defineProperty(fake, "result", { get: () => real.result });
        Object.defineProperty(fake, "error", { get: () => real.error });
        for (const ev of ["onupgradeneeded", "onsuccess", "onerror"] as const) {
          real[ev] = (e: Event) => (fake[ev] as ((e: Event) => void) | undefined)?.(e);
        }
      });
      return fake as unknown as IDBOpenDBRequest;
    };
  }

  // After a reload the active child is the default one. A sibling's
  // interrupted visit went up to her own record, but "Preparar resumen" then
  // read the default child's.
  test("a sibling's interrupted visit makes her the active child", async ({ page, context }) => {
    const [, nora] = await seedAccount(page, context, ["Leo", "Nora"]);
    const startedAt = Date.now() - 2 * 24 * 60 * 60 * 1000;
    await seedDraft(page, { profileId: nora, startedAt, policyVersion: "2026-01-01" });
    const form: Record<string, string> = {};
    await page.route("**/api/backend/documents", async (route) => {
      const text = (route.request().postDataBuffer() ?? Buffer.alloc(0)).toString("latin1");
      for (const field of ["profile_id", "consent_policy_version"]) {
        const m = text.match(new RegExp(`name="${field}"\\r\\n\\r\\n([^\\r]+)`));
        if (m) form[field] = m[1];
      }
      form.filename = text.match(/filename="([^"]+)"/)?.[1] ?? "";
      const id = "00000000-0000-0000-0000-0000000000d2";
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id, status: "processing" }),
      });
    });
    await page.route("**/api/backend/documents/*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-0000000000d2", status: "ready" }),
      }),
    );
    await page.reload();

    await expect(page.getByText("la consulta de Nora", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "Subir la grabación interrumpida" }).click();
    await expect(page.getByText("Consulta guardada", { exact: false })).toBeVisible({
      timeout: 15_000,
    });
    expect(form.profile_id).toBe(nora);
    // The consent she gave when she recorded, and the day she recorded.
    expect(form.consent_policy_version).toBe("2026-01-01");
    expect(form.filename).toBe(`consulta-${new Date(startedAt).toISOString().slice(0, 10)}.webm`);

    let created: { profile_id?: string } | null = null;
    await page.route("**/api/backend/briefings", (route) => {
      if (route.request().method() !== "POST") return route.continue();
      created = route.request().postDataJSON();
      return route.fulfill({ status: 500 });
    });
    await page.getByRole("link", { name: "Preparar resumen para el pediatra" }).click();
    await page.getByRole("combobox", { name: "¿Qué médico verás?" }).selectOption({ label: "Pediatría" });
    await page.getByRole("button", { name: "Generar briefing" }).click({ timeout: 60_000 });
    await expect.poll(() => created?.profile_id).toBe(nora);
  });

  // "Grabar" waits for the device check. A tap before it started a new
  // draft, whose clear() erased the interrupted visit before it was offered,
  // on exactly the reopen-after-a-killed-tab path.
  test("'Grabar' waits for the device check, so an early start cannot erase a visit", async ({
    page,
    context,
  }) => {
    const [leo] = await seedAccount(page, context, ["Leo"]);
    await seedDraft(page, { profileId: leo, startedAt: Date.now() - 60_000 });
    await page.addInitScript(holdDeviceCheck);
    await page.reload();
    await page.getByRole("checkbox").check();
    // React has read the tick (the hint is gone), and "Grabar" still waits.
    // Generous: on a busy dev server hydration alone can take seconds.
    await expect(page.getByText("Marca la casilla de arriba")).toHaveCount(0, { timeout: 60_000 });
    await expect(page.getByRole("button", { name: "Grabar", exact: true })).toBeDisabled();

    await page.evaluate(() =>
      (window as unknown as { __releaseDraftCheck: () => void }).__releaseDraftCheck(),
    );
    await expect(page.getByText("la consulta de Leo", { exact: false })).toBeVisible();
    await expect.poll(() => draftCount(page)).toBe(3);
  });

  // ...but a device store that never answers (some WebKit builds on a cold
  // start) must not keep the mic shut: the backup is lost, not the visit.
  test("a device store that never answers does not keep 'Grabar' disabled", async ({
    page,
    context,
  }) => {
    await seedAccount(page, context, ["Leo"]);
    await page.addInitScript(holdDeviceCheck);
    await page.reload();
    await page.getByRole("checkbox").check();
    const start = page.getByRole("button", { name: "Grabar", exact: true });
    await expect(start).toBeEnabled({ timeout: 10_000 });
    await start.click();
    await expect(page.getByRole("status")).toContainText("Grabando");
  });

  // "Descartarla" sits right under the primary button and erases a visit
  // that cannot be recorded again: two taps, like the kill switch.
  test("dropping an interrupted visit takes two taps", async ({ page, context }) => {
    const [leo] = await seedAccount(page, context, ["Leo"]);
    await seedDraft(page, { profileId: leo, startedAt: Date.now() - 60_000 });
    await page.reload();

    await page.getByRole("button", { name: "Descartarla" }).click();
    const confirm = page.getByRole("button", { name: "Toca otra vez para borrarla" });
    await expect(confirm).toBeVisible();
    await expect(page.getByText("la consulta de Leo", { exact: false })).toBeVisible();
    expect(await draftCount(page)).toBe(3);

    await confirm.click();
    await expect(page.getByRole("button", { name: "Grabar", exact: true })).toBeVisible();
    await expect.poll(() => draftCount(page)).toBe(0);
  });

  // A draft never offered (another account's child on a shared phone) used
  // to stay on the device for good. After 7 days it is deleted, not offered.
  test("a draft older than 7 days is deleted, not offered", async ({ page, context }) => {
    const [leo] = await seedAccount(page, context, ["Leo"]);
    await seedDraft(page, { profileId: leo, startedAt: Date.now() - 8 * 24 * 60 * 60 * 1000 });
    await page.reload();
    await page.getByRole("checkbox").check();
    await expect(page.getByRole("button", { name: "Grabar", exact: true })).toBeEnabled();
    await expect(page.getByText("se cortó antes de subirse", { exact: false })).toHaveCount(0);
    await expect.poll(() => draftCount(page)).toBe(0);
  });

  async function recordPastOneChunk(page: Page) {
    await page.goto("/es/dashboard/consulta/grabar");
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Grabar" }).click();
    await expect(page.getByRole("status")).toContainText("Grabando");
    // MediaRecorder hands over a chunk every second; wait for the first one
    // (meta + at least one chunk on the device).
    await expect.poll(() => draftCount(page), { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  }

  test("a reload mid-visit offers to upload it, for her child, and then forgets it", async ({
    page,
    context,
  }) => {
    const { cookie, userId } = await seedUserAndSessionCookie(
      `e2e-consulta-draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
    );
    const profileId = await seedProfile(userId, {
      displayName: "Leo",
      dateOfBirth: isoMonthsAgo(9),
    });
    await context.addCookies([cookie]);
    const form: Record<string, string> = {};
    let uploads = 0;
    let bytes = 0;
    await page.route("**/api/backend/documents", async (route) => {
      uploads += 1;
      const body = route.request().postDataBuffer() ?? Buffer.alloc(0);
      bytes = body.length;
      const text = body.toString("latin1");
      for (const field of ["source", "profile_id", "consent_policy_version", "interrupted"]) {
        const m = text.match(new RegExp(`name="${field}"\\r\\n\\r\\n([^\\r]+)`));
        if (m) form[field] = m[1];
      }
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-0000000000d1", status: "processing" }),
      });
    });
    await page.route("**/api/backend/documents/*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-0000000000d1", status: "ready" }),
      }),
    );

    await recordPastOneChunk(page);
    // The guard arms beforeunload; she confirms the reload, as on a phone.
    page.on("dialog", (dialog) => void dialog.accept());
    await page.reload();
    expect(uploads).toBe(0);

    await expect(page.getByText("se cortó antes de subirse", { exact: false })).toBeVisible();
    // Named, so a mother of two knows whose visit it is.
    await expect(page.getByText("la consulta de Leo", { exact: false })).toBeVisible();
    await expect(page.getByRole("button", { name: "Grabar", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Subir la grabación interrumpida" }).click();
    await expect(page.getByText("Consulta guardada", { exact: false })).toBeVisible({ timeout: 15_000 });
    expect(uploads).toBe(1);
    expect(bytes).toBeGreaterThan(1_000);
    expect(form.source).toBe("consulta");
    expect(form.profile_id).toBe(profileId);
    expect(form.consent_policy_version).toBe("2026-08-17");
    // Third QA wave 2026-11-13: a cut inside "treinta y ocho" was summarised as
    // "sube de 30" with no mark. The server is told the recording was cut, so
    // the summary leaves out the last sentence and says so.
    expect(form.interrupted).toBe("true");

    // Uploaded: nothing stays on the device and nothing is offered again.
    await expect.poll(() => draftCount(page)).toBe(0);
  });

  // Verification QA 2026-11-13: with 10 s chunks only, a reload at 15 s lost
  // the doctor's last answer and one at 6 s lost the whole visit. A chunk now
  // comes every second and one more when the page goes away, and what the
  // device kept must still be one file the pipeline can read.
  test("a reload 4 s in keeps every second, as one file that decodes", async ({ page, context }) => {
    const { cookie, userId } = await seedUserAndSessionCookie(
      `e2e-consulta-draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
    );
    await seedProfile(userId, { displayName: "Leo", dateOfBirth: isoMonthsAgo(9) });
    await context.addCookies([cookie]);
    let body: Buffer = Buffer.alloc(0);
    await page.route("**/api/backend/documents", async (route) => {
      body = route.request().postDataBuffer() ?? Buffer.alloc(0);
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-0000000000d4", status: "processing" }),
      });
    });
    await page.route("**/api/backend/documents/*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-0000000000d4", status: "ready" }),
      }),
    );
    await page.goto("/es/dashboard/consulta/grabar");
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Grabar" }).click();
    await expect(page.getByRole("status")).toContainText("Grabando");
    const began = Date.now();
    await page.waitForTimeout(4_000);
    page.on("dialog", (dialog) => void dialog.accept());
    const recorded = (Date.now() - began) / 1000;
    await page.reload();

    await page.getByRole("button", { name: "Subir la grabación interrumpida" }).click();
    await expect(page.getByText("Consulta guardada", { exact: false })).toBeVisible({ timeout: 15_000 });
    // The file part of the multipart body: after the part's blank line, up
    // to the CRLF before the next boundary.
    const raw = body.toString("latin1");
    const boundary = raw.slice(0, raw.indexOf("\r\n"));
    const start = raw.indexOf("\r\n\r\n", raw.indexOf('filename="')) + 4;
    const file = body.subarray(start, raw.indexOf(`\r\n${boundary}`, start));
    const seconds = await page.evaluate(async (b64) => {
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const audio = await new OfflineAudioContext(1, 1, 48_000).decodeAudioData(bytes.buffer);
      return audio.duration;
    }, file.toString("base64"));
    // About a second may be lost to a tab killed without warning; never more.
    expect(seconds).toBeGreaterThanOrEqual(recorded - 1.5);
  });

  test("hiding or leaving the page asks the recorder for the audio so far", async ({
    page,
    context,
  }) => {
    const { cookie, userId } = await seedUserAndSessionCookie(
      `e2e-consulta-draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
    );
    await seedProfile(userId, { displayName: "Leo", dateOfBirth: isoMonthsAgo(9) });
    await context.addCookies([cookie]);
    await page.addInitScript(() => {
      const w = window as unknown as { __requests: number };
      w.__requests = 0;
      const real = MediaRecorder.prototype.requestData;
      MediaRecorder.prototype.requestData = function (this: MediaRecorder) {
        w.__requests += 1;
        return real.call(this);
      };
    });
    await recordPastOneChunk(page);
    const requests = () => page.evaluate(() => (window as unknown as { __requests: number }).__requests);
    expect(await requests()).toBe(0);
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
      document.dispatchEvent(new Event("visibilitychange"));
      delete (document as unknown as { visibilityState?: string }).visibilityState;
    });
    await expect.poll(requests).toBe(1);
    await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    await expect.poll(requests).toBe(2);
    // Still recording: a flush is not a stop.
    await expect(page.getByRole("status")).toContainText("Grabando");
  });

  test("the kill switch leaves nothing of the visit on the device", async ({ page, context }) => {
    const { cookie, userId } = await seedUserAndSessionCookie(
      `e2e-consulta-draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
    );
    await seedProfile(userId, { displayName: "Leo", dateOfBirth: isoMonthsAgo(9) });
    await context.addCookies([cookie]);
    await page.route("**/api/backend/consent-events", (route) =>
      route.fulfill({ status: 201, contentType: "application/json", body: "{}" }),
    );

    await recordPastOneChunk(page);
    await page.getByRole("button", { name: "El profesional se opone" }).click();
    await page.getByRole("button", { name: "Toca otra vez para descartar la grabación" }).click();
    await expect(page.getByText("Grabación descartada", { exact: false })).toBeVisible();
    await expect.poll(() => draftCount(page)).toBe(0);
    await page.reload();
    await expect(page.getByRole("button", { name: "Grabar", exact: true })).toBeVisible();
    await page.waitForTimeout(1_000); // the draft is read right after mount
    await expect(page.getByText("se cortó antes de subirse", { exact: false })).toHaveCount(0);
  });
});

test("professionals page is public in 3 locales", async ({ page }) => {
  for (const locale of ["es", "en", "fr"]) {
    await page.goto(`/${locale}/profesionales`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(page.url()).not.toContain("signin");
  }
});
