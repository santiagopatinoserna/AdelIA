import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

// "La demo es la app real" (Santiago, 2026-11-06), walked end to end against
// the real API with no LLM key: the questions are red flags, which the
// deterministic guard answers before any model, so every turn is real and is
// stored. Covers: landing -> guest panel with Lucía and her answer -> a
// follow-up that carries the history -> the record button opens the real
// recorder -> "Hoy con Lucía" -> reload keeps the session and the
// conversation -> erasure in Settings.

const SHOTS = join(homedir(), "dev/adelia-design/shots/demo-app");
const FIRST = "Mi bebé ha convulsionado y no reacciona";
const SECOND = "Ahora ha convulsionado otra vez, ¿qué hago?";

test.describe.configure({ mode: "serial" });

test("a visitor's question opens her own space with Lucía, and it is kept", async ({ page }) => {
  test.setTimeout(180_000);
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/es");
  await expect(page.getByText(/se guarda en tu espacio con Lucía/)).toBeVisible();

  const turns: Record<string, unknown>[] = [];
  await page.route("**/api/backend/agent/turn", async (route) => {
    turns.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.continue();
  });

  await page.locator("#demo-question").fill(FIRST);
  await page.getByRole("button", { name: "Preguntar", exact: true }).click();

  // The real panel, as a guest, with her question answered once.
  await expect(page).toHaveURL(/\/es\/dashboard\/?$/, { timeout: 30_000 });
  const thread = page.getByTestId("agent-message");
  await expect(thread.filter({ hasText: FIRST })).toHaveCount(1);
  await expect(page.locator('[data-role="assistant"]').first()).toContainText("112", {
    timeout: 30_000,
  });
  expect(turns).toHaveLength(1);
  expect(turns[0].message).toBe(FIRST);
  await expect(page.getByTestId("save-account")).toBeVisible();
  await page.screenshot({ path: join(SHOTS, "panel-first-answer-390.png") });

  // Where to keep asking about the same thing, and the follow-up uses it.
  const field = page.getByPlaceholder("Pregunta más sobre esto");
  await expect(field).toBeVisible();
  await field.fill(SECOND);
  await field.press("Enter");
  await expect(page.locator('[data-role="assistant"]')).toHaveCount(2, { timeout: 30_000 });
  await expect(page.locator('[data-role="assistant"]').nth(1)).toContainText("112");
  expect(turns).toHaveLength(2);
  const history = turns[1].history as { role: string; content: string }[];
  expect(history[0]).toEqual({ role: "user", content: FIRST });
  expect(history[1].role).toBe("assistant");
  expect(history[1].content).toContain("112");
  expect(typeof turns[1].thread_id).toBe("string");

  // The record button, on the main screen, without unfolding anything.
  const record = page.getByTestId("record-consult");
  await expect(record).toBeVisible();
  await expect(record).toBeInViewport();
  await record.click();
  await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar/);
  const start = page.getByRole("button", { name: "Grabar" });
  await expect(start).toBeDisabled();
  await page.getByRole("checkbox").check();
  await expect(start).toBeEnabled();
  await page.screenshot({ path: join(SHOTS, "recorder-from-panel-390.png") });

  // Back on the panel: her baby and "Hoy con Lucía", read from her seeded record.
  await page.goto("/es/dashboard");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Lucía");
  const today = page.getByTestId("today-card");
  await expect(today).toBeVisible();
  await expect(today).toContainText("Lucía");
  await expect(today).toContainText(/5\s?h/);
  await page.screenshot({ path: join(SHOTS, "panel-today-lucia-390.png") });

  // The conversation is stored: one tap brings it back, and back again to "Hoy".
  await page.getByTestId("continue-conversation").click();
  await expect(thread.filter({ hasText: FIRST })).toHaveCount(1);
  await expect(page.locator('[data-role="assistant"]')).toHaveCount(2);
  await page.getByTestId("new-conversation").click();
  await expect(today).toBeVisible();

  // A reload keeps her session and everything she did.
  await page.reload();
  await expect(page).toHaveURL(/\/es\/dashboard\/?$/);
  await expect(page.getByTestId("today-card")).toContainText("Lucía");
  await page.getByTestId("continue-conversation").click();
  await expect(thread.filter({ hasText: SECOND })).toHaveCount(1);
  expect(turns).toHaveLength(2);

  // Erasure, as for any account (GDPR art. 17).
  await page.goto("/es/dashboard/settings");
  await expect(page.getByText(/Ahora usas AdelIA sin cuenta/)).toBeVisible();
  await page.getByRole("checkbox").check();
  await page.getByLabel("Escribe Lucía para confirmar").fill("lucia");
  await page.getByRole("button", { name: /Eliminar mi cuenta/ }).click();
  await expect(page).toHaveURL(/\/es\/?$/, { timeout: 30_000 });
  await page.goto("/es/dashboard");
  await expect(page).toHaveURL(/\/es\/signin/);
});

test("the landing's record button opens the real recorder in a new space", async ({ page }) => {
  await page.goto("/es");
  await page.getByTestId("landing-record").click();
  await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar/, { timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Grabar" })).toBeDisabled();
});
