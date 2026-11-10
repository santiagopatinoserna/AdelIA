import { expect, test } from "@playwright/test";
import { join } from "node:path";

import { eraseGuest, sessionUserId } from "../browser";
import { saveGuest } from "../guests";
import { URGENT_QUESTIONS } from "../kit";
import { type Issue, type JourneyStep, VIEWPORTS, journeyTotals } from "./kit";
import { RUN_DIR, errorIssues, issues, note, openContext, record, shot } from "./page";

// The whole way, as one mother would go, with a guest of her own (the
// battery's is already gone, 50): the landing, a red flag typed there (it
// opens her space with Lucía and the guard answers in code), a follow-up in
// the same thread, a reload and «Seguir la conversación», the recorder
// (never «Grabar»), «Más», Telegram closed if it shows, Settings and erasing
// her. Every tap is counted and every step timed; a step that breaks stops
// the journey and is the report's "journey-broken" line. The guest is erased
// in Settings, or by the cleanup below if the journey broke first.

const [FIRST, SECOND] = URGENT_QUESTIONS;
const NAME = "Recorrido completo (390, es, claro)";

test("60 Recorrido completo: portada → urgencia → hilo → recargar → grabar → Más → Ajustes → borrar", async ({ browser, baseURL }) => {
  const { context, page, guard, errors } = await openContext(browser, {
    viewport: VIEWPORTS[1], scheme: "light", locale: "es", guest: false, baseURL: baseURL!,
  });
  const steps: JourneyStep[] = [];
  const found: Issue[] = [];
  const guest = { id: null as string | null, erased: false };
  let broken = false;

  async function step(name: string, run: (tap: () => void) => Promise<void>) {
    if (broken) {
      steps.push({ name, taps: 0, ms: 0, ok: false });
      return;
    }
    let taps = 0;
    const t0 = Date.now();
    try {
      await run(() => taps++);
      steps.push({ name, taps, ms: Date.now() - t0, ok: true });
    } catch (e) {
      broken = true;
      steps.push({ name, taps, ms: Date.now() - t0, ok: false });
      found.push({ kind: "journey-broken", where: NAME, detail: `${name}: ${(e as Error).message.split("\n")[0].slice(0, 160)}` });
      await shot(page, `60-broken`).catch(() => {});
    }
  }

  const field = page.getByTestId("agent-canvas").locator("textarea");
  const answers = page.locator('[data-role="assistant"]');
  const nav = (path: string) => page.locator(`nav[data-nav-lock] a[href$="${path}"]`);

  try {
    await step("Abrir la portada", async () => {
      await page.goto("/es");
      await expect(page.locator("#demo-question")).toBeVisible();
    });

    await step("Preguntar una urgencia en la portada (abre su espacio con Lucía)", async (tap) => {
      tap();
      await page.locator("#demo-question").click();
      await page.locator("#demo-question").fill(FIRST);
      tap();
      await page.locator('[data-track="landing-ask"]').click();
      await expect(page).toHaveURL(/\/es\/dashboard/, { timeout: 30_000 });
      guest.id = await sessionUserId(page);
      if (guest.id) {
        saveGuest(RUN_DIR, { id: guest.id, erased: false, detail: "journey guest, opened by 60" });
        await context.storageState({ path: join(RUN_DIR, `guest-${guest.id}.json`) });
      }
      await expect(answers.first()).toContainText("112", { timeout: 30_000 });
      await shot(page, "60-1-urgencia");
    });

    await step("Seguir el hilo con otra pregunta", async (tap) => {
      await expect(field).toHaveAttribute("placeholder", "Pregunta más sobre esto");
      tap();
      await field.click();
      await field.fill(SECOND);
      tap();
      await page.getByTestId("agent-canvas").locator(".ad-btn-primary").click();
      await expect(answers).toHaveCount(2, { timeout: 30_000 });
      await expect(answers.nth(1)).toContainText("112");
      await shot(page, "60-2-hilo");
    });

    await step("Recargar y seguir la conversación", async (tap) => {
      tap(); // pull to refresh
      await page.reload();
      tap();
      await page.getByTestId("continue-conversation").click();
      await expect(page.getByTestId("agent-message")).toHaveCount(4);
      await shot(page, "60-3-seguir");
    });

    await step("Abrir la grabadora de la consulta (sin grabar)", async (tap) => {
      tap();
      await page.getByTestId("record-consult").click();
      await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar/);
      await expect(page.getByRole("checkbox")).toBeVisible();
      await expect(page.getByRole("button", { name: "Grabar", exact: true })).toBeDisabled();
      await shot(page, "60-4-grabadora");
    });

    await step("Volver al panel y abrir «Más»", async (tap) => {
      tap();
      await nav("/dashboard").click();
      await expect(page.getByTestId("panel-more")).toBeVisible();
      tap();
      await page.getByTestId("panel-more").locator(":scope > summary").click();
      await expect(page.getByTestId("save-account")).toBeVisible();
      await shot(page, "60-5-mas");
    });

    await step("Cerrar Telegram si aparece", async (tap) => {
      const telegram = page.getByTestId("panel-suggestion").filter({ hasText: /Telegram/ });
      if ((await telegram.count()) === 0) {
        note("Telegram: no aparece (invitada)");
        return;
      }
      tap();
      await telegram.first().getByRole("button", { name: /:/ }).click();
      await expect(telegram).toHaveCount(0);
    });

    await step("Ajustes y borrar su espacio", async (tap) => {
      tap();
      await nav("/dashboard/settings").click();
      await expect(page).toHaveURL(/\/es\/dashboard\/settings/);
      const danger = page.locator("section").filter({ has: page.locator("#confirm-delete") });
      tap();
      await danger.getByRole("checkbox").check();
      tap();
      await page.getByLabel("Escribe Lucía para confirmar").fill("Lucía");
      const deleted = page.waitForResponse(
        (r) => r.url().endsWith("/api/backend/users/me") && r.request().method() === "DELETE",
      );
      tap();
      await danger.getByRole("button", { name: /Eliminar mi cuenta/ }).click();
      expect((await deleted).status(), "DELETE /users/me").toBe(204);
      guest.erased = true;
      if (guest.id) saveGuest(RUN_DIR, { id: guest.id, erased: true, detail: "erased in Settings by the journey" });
      await expect(page).toHaveURL(/\/es\/?$/, { timeout: 30_000 });
      expect(await sessionUserId(page), "session after erasure").toBeNull();
      await shot(page, "60-6-borrada");
    });
  } finally {
    if (!guest.erased) {
      const id = guest.id ?? (await sessionUserId(page).catch(() => null));
      if (id) {
        const outcome = await eraseGuest(page, id).catch((e: Error) => ({ erased: false, detail: `cleanup failed: ${e.message}` }));
        saveGuest(RUN_DIR, { id, ...outcome });
      }
    }
    await context.close();
  }

  record({ type: "journey", name: NAME, steps });
  const t = journeyTotals(steps);
  found.push(...errorIssues(errors, NAME));
  issues(found);
  note(`${t.taps} taps, ${(t.ms / 1000).toFixed(1)} s; ${steps.map((s) => `${s.name}: ${s.taps} / ${(s.ms / 1000).toFixed(1)} s`).join("; ")}`);
  expect(guard.violations, "requests the model guard stopped").toEqual([]);
  expect(guard.turns, "two red-flag turns").toHaveLength(2);
  expect(found).toEqual([]);
});
