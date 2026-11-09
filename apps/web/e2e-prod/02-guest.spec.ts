import { type BrowserContext, type Page, expect, test } from "@playwright/test";

import { saveGuest } from "./guests";
import { foreignAges, monthsInGrowthMark, URGENT_QUESTIONS } from "./kit";
import {
  armModelGuard,
  eraseGuest,
  type ModelGuard,
  note,
  pageErrors,
  sessionUserId,
  shot,
} from "./browser";

// Checks 2 to 4, on ONE guest space, in order: the landing's record button
// opens her space with Lucía (2), a conversation the model never answers
// because both questions are red flags (3), and her erasure from Settings
// (4). afterAll erases the guest if anything failed before check 4 got
// there, so no run leaves a guest behind on production.

const RUN_DIR = process.env.PROD_SMOKE_RUN_DIR!;
const [FIRST, SECOND] = URGENT_QUESTIONS;

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
let guard: ModelGuard;
let errors: string[];
const guest: { id: string | null; erased: boolean } = { id: null, erased: false };

test.beforeAll(async ({ browser }, testInfo) => {
  const use = testInfo.project.use;
  context = await browser.newContext({
    baseURL: use.baseURL,
    viewport: use.viewport,
    locale: use.locale,
    serviceWorkers: use.serviceWorkers,
    extraHTTPHeaders: use.extraHTTPHeaders,
  });
  guard = await armModelGuard(context);
  page = await context.newPage();
  errors = pageErrors(page);
});

test.afterAll(async () => {
  try {
    // Also a guest whose id was never read: the session cookie is the proof.
    const id = guest.id ?? (await sessionUserId(page).catch(() => null));
    if (id && !guest.erased) {
      const outcome = await eraseGuest(page, id).catch((e: Error) => ({
        erased: false,
        detail: `cleanup failed: ${e.message}`,
      }));
      saveGuest(RUN_DIR, { id, ...outcome });
    }
  } finally {
    await context.close();
  }
});

test("2 Invitada: grabar abre su espacio con Lucía", async () => {
  await page.goto("/es");
  await page.getByTestId("landing-record").click();
  await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar/, { timeout: 30_000 });

  guest.id = await sessionUserId(page);
  expect(guest.id, "a guest session after the record button").toBeTruthy();
  saveGuest(RUN_DIR, { id: guest.id!, erased: false, detail: "created by check 2" });

  // The consent step: "Grabar" waits for the box. Never pressed here, that
  // would send audio to speech-to-text.
  await expect(page.getByRole("button", { name: "Grabar", exact: true })).toBeDisabled();
  await expect(page.getByRole("checkbox")).toBeVisible();
  await shot(page, RUN_DIR, "02-recorder-consent");

  await page.goto("/es/dashboard");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Lucía");
  await expect(page.getByTestId("today-card")).toContainText("Hoy con Lucía");

  // "Grabar la consulta" on the first screen, without scrolling.
  const record = page.getByTestId("record-consult");
  await expect(record).toBeVisible();
  await expect(record).toHaveText("Grabar la consulta");
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  const box = (await record.boundingBox())!;
  expect(box.y + box.height, "record button inside the first 844px").toBeLessThanOrEqual(844);

  // "Guardar mi cuenta", once, under the folded "Más" (2026-11-09), and no
  // Telegram offer for a guest.
  await page.getByTestId("panel-more").locator(":scope > summary").click();
  await expect(page.getByTestId("save-account")).toHaveText("Guardar mi cuenta");
  await expect(page.getByTestId("save-account")).toHaveCount(1);
  await expect(page.getByText(/Telegram/)).toHaveCount(0);

  // The example question names no age but Lucía's.
  const mark = await page.getByTestId("growth-mark").innerText();
  const months = monthsInGrowthMark(mark);
  expect(months, `Lucía's age in "${mark}"`).not.toBeNull();
  const example = (await page.getByTestId("ask-example").innerText()).trim();
  expect(foreignAges(example, months), `example "${example}" for ${months} months`).toEqual([]);

  await shot(page, RUN_DIR, "02-panel-lucia");
  expect(errors, "uncaught page errors").toEqual([]);
  note(`guest ${guest.id!.slice(0, 8)}; Lucía ${months} months; example "${example}"`);
});

test("3 Conversación sin modelo: dos urgencias y el hilo vuelve", async () => {
  await page.goto("/es/dashboard");
  const field = page.getByTestId("agent-canvas").locator("textarea");
  const answers = page.locator('[data-role="assistant"]');
  const thread = page.getByTestId("agent-message");

  await field.fill(FIRST);
  await field.press("Enter");
  await expect(answers.first()).toContainText("112", { timeout: 30_000 });
  await expect(field).toHaveAttribute("placeholder", "Pregunta más sobre esto");

  await field.fill(SECOND);
  await field.press("Enter");
  await expect(answers).toHaveCount(2, { timeout: 30_000 });
  await expect(answers.nth(1)).toContainText("112");
  await expect(thread).toHaveCount(4);

  expect(guard.turns).toHaveLength(2);
  expect(guard.turns[0].history ?? []).toEqual([]);
  const history = guard.turns[1].history as { role: string; content: string }[];
  expect(history[0]).toEqual({ role: "user", content: FIRST });
  expect(history[1].role).toBe("assistant");
  expect(history[1].content).toContain("112");
  expect(typeof guard.turns[1].thread_id).toBe("string");
  await shot(page, RUN_DIR, "03-conversation");

  // After a reload the conversation is one tap away, whole.
  await page.reload();
  const resume = page.getByTestId("continue-conversation");
  await expect(resume).toHaveText("Seguir la conversación");
  await resume.click();
  await expect(thread).toHaveCount(4);
  await expect(thread.filter({ hasText: FIRST })).toHaveCount(1);
  await expect(thread.filter({ hasText: SECOND })).toHaveCount(1);
  await shot(page, RUN_DIR, "03-resumed");

  expect(guard.violations, "requests the model guard stopped").toEqual([]);
  expect(guard.turns, "no turn sent by the reload").toHaveLength(2);
  expect(errors, "uncaught page errors").toEqual([]);
  note(`2 red-flag turns, history carried, thread resumed after reload; ${guard.modelRequests.length} answering-path requests, all allowed`);
});

test("4 Limpieza: borrar la invitada desde Ajustes", async () => {
  await page.goto("/es/dashboard/settings");
  const danger = page.locator("section").filter({ has: page.locator("#confirm-delete") });
  await danger.getByRole("checkbox").check();
  await page.getByLabel("Escribe Lucía para confirmar").fill("Lucía");
  const deleted = page.waitForResponse(
    (r) => r.url().endsWith("/api/backend/users/me") && r.request().method() === "DELETE",
  );
  await danger.getByRole("button", { name: /Eliminar mi cuenta/ }).click();
  const res = await deleted;
  expect(res.status(), "DELETE /users/me").toBe(204);
  guest.erased = true;
  saveGuest(RUN_DIR, { id: guest.id!, erased: true, detail: "erased in Settings" });

  await expect(page).toHaveURL(/\/es\/?$/, { timeout: 30_000 });
  expect(await sessionUserId(page), "session after erasure").toBeNull();
  await page.goto("/es/dashboard");
  await expect(page).toHaveURL(/\/es\/signin/);
  await shot(page, RUN_DIR, "04-after-erase");
  note(`guest ${guest.id!.slice(0, 8)} erased in Settings; /dashboard now goes to sign-in`);
});
