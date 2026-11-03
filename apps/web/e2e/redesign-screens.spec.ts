import { randomUUID } from "node:crypto";

import { expect, test, type Browser, type Page } from "@playwright/test";
import { Pool } from "pg";

import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";
import { seedUserAndSessionCookie } from "./utils/session";

// The mother-first redesign (docs/design/REDISENO.md, apps/web/UX_PRINCIPLES.md
// rules 12 to 17): what each screen now promises a mother with one free hand.
// Demo answers are synthetic and mocked; only their fixed frames (the
// red-flag "Llama al 112") mirror what the API writes.
const PHONE = { width: 390, height: 844 };
const WIDE = { width: 1280, height: 800 };
const copy = { es, en, fr };
const citation = {
  tag: "ev_1", source_id: "redesign-source", chunk_id: "redesign-chunk",
  title: "Título de la fuente de prueba", organization: "Institución de prueba",
  year: 2026, url: "https://example.org/source", snippet: "Fragmento de prueba.",
};

async function ask(page: Page, locale: "es" | "en" | "fr", payload: Record<string, unknown>) {
  await page.route("**/api/demo/ask", (route) => route.fulfill({ json: {
    evidence_citations: [citation], disclaimer: "Aviso clínico.", ...payload,
  } }));
  await page.goto(`/${locale}`);
  await page.locator("#demo-question").fill("Pregunta de prueba");
  await page.getByRole("button", { name: copy[locale].demo.askCta, exact: true }).click();
}

function longPlan(locale: "es" | "en" | "fr") {
  const p = copy[locale].demo.plan;
  const bullets = (n: number) =>
    Array.from({ length: n }, (_, i) => `- Línea de prueba número ${i + 1} con algo de texto [ev_1].`).join("\n");
  return `Apertura de prueba [ev_1].\n\n## ${p.today}\n${bullets(6)}\n\n## ${p.watch}\n${bullets(6)}\n\n` +
    `## ${p.doctor}\n${bullets(4)}\n\n## ${p.remember}\n${bullets(3)}`;
}

test.describe("demo answers", () => {
  test.use({ viewport: PHONE });

  for (const locale of ["es", "en", "fr"] as const) {
    test(`${locale}: the plan map jumps to «${copy[locale].demo.plan.doctor}»`, async ({ page }) => {
      const p = copy[locale].demo.plan;
      await ask(page, locale, { kind: "answer", intent: "plan", answer: longPlan(locale) });
      const map = page.getByTestId("plan-map");
      await expect(map).toBeVisible();
      await expect(map.getByRole("button")).toHaveText([p.today, p.watch, p.doctor, p.remember]);
      await map.getByRole("button", { name: p.doctor }).click();
      const heading = page.getByTestId("plan-section-doctor").getByRole("heading");
      await expect(heading).toBeFocused();
      await expect(heading).toBeInViewport();
      // Mid-plan, the next question is still under the thumb.
      await expect(page.getByTestId("ask-another")).toBeInViewport();
    });

    test(`${locale}: a red flag leads with a one-tap call from the fixed frame`, async ({ page }) => {
      const frame = { es: "Llama al 112", en: "Call 112", fr: "Appelez le 112" }[locale];
      await ask(page, locale, {
        kind: "red_flag", intent: null,
        answer: `Texto fijo de prueba.\n\n${frame} o acude ahora a urgencias.`,
      });
      const call = page.getByTestId("call-emergency");
      await expect(call).toHaveAttribute("href", "tel:112");
      await expect(call).toHaveText(copy[locale].demo.callEmergency.replace("{number}", "112"));
      const box = await call.boundingBox();
      const text = await page.getByText("Texto fijo de prueba.").boundingBox();
      expect(box!.y, "the call button comes before the reply").toBeLessThan(text!.y);
      expect(box!.height).toBeGreaterThanOrEqual(52);
    });
  }

  test("es: a red flag whose fixed reply names no number has no call button", async ({ page }) => {
    await ask(page, "es", { kind: "red_flag", intent: null, answer: "Acude hoy a tu pediatra." });
    await expect(page.getByTestId("urgent-block")).toBeVisible();
    await expect(page.getByTestId("call-emergency")).toHaveCount(0);
  });

  for (const locale of ["es", "en", "fr"] as const) {
    test(`${locale}: no evidence and sources-only carry their own titles`, async ({ page }) => {
      const m = copy[locale].demo;
      await ask(page, locale, {
        kind: "no_evidence", intent: "plan", evidence_citations: [],
        answer: "No tengo evidencia clínica sobre esto en mi biblioteca.",
      });
      await expect(page.locator("#demo-answer-title")).toHaveText(m.noEvidenceTitle);
      await expect(page.locator("#demo-answer-title")).not.toHaveText(m.answerTitle);

      await page.unrouteAll();
      await ask(page, locale, { kind: "evidence_only", intent: "plan", answer: "" });
      await expect(page.locator("#demo-answer-title")).toHaveText(m.evidenceOnlyTitle);
      // The sources are the answer here, so they are open, not folded.
      await expect(page.getByTestId("answer-depth")).toHaveCount(0);
      await expect(page.getByText(citation.title).first()).toBeVisible();
    });
  }
});

function pgPool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

const seededUserIds: string[] = [];

test.afterAll(async () => {
  if (seededUserIds.length === 0) return;
  const pool = pgPool();
  try {
    await pool.query(`DELETE FROM documents WHERE user_id = ANY($1::uuid[])`, [seededUserIds]);
    await pool.query(`DELETE FROM users WHERE id = ANY($1::uuid[])`, [seededUserIds]);
  } finally {
    await pool.end();
  }
});

// processed_at set: a pending row would be requeued as a real pipeline.
async function insertDocument(userId: string) {
  const pool = pgPool();
  try {
    await pool.query(
      `INSERT INTO documents (id, user_id, source, mime_type, s3_key, raw_text, processed_at)
       VALUES (gen_random_uuid(), $1, 'web', 'application/pdf', $2, 'texto de prueba', now())`,
      [userId, `users/${userId}/${randomUUID()}-cartilla.pdf`],
    );
  } finally {
    await pool.end();
  }
}

async function openAs(browser: Browser, tag: string, viewport = PHONE) {
  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-rd-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
  );
  seededUserIds.push(userId);
  const phone = viewport.width < 768;
  const context = await browser.newContext({ viewport, isMobile: phone, hasTouch: phone });
  await context.addCookies([cookie]);
  return { context, page: await context.newPage(), userId };
}

async function tabBarTop(page: Page) {
  const bar = await page.getByRole("navigation", { name: es.dashboard.navHome }).boundingBox();
  return bar!.y;
}

test("Historial opens on the documents, the five tools in one row", async ({ browser }) => {
  const { context, page, userId } = await openAs(browser, "historial");
  await insertDocument(userId);
  await page.goto("/es/dashboard/overview");
  const title = page.getByRole("heading", { level: 1, name: es.dashboard.title });
  const tools = page.getByRole("navigation", { name: es.dashboard.toolsLabel });
  await expect(title).toBeVisible();
  await expect(tools.getByRole("link")).toHaveCount(5);
  // Upload and Modo Consulta live in the tab bar; the page does not repeat them.
  for (const href of ["/es/dashboard/upload", "/es/dashboard/consulta"]) {
    await expect(tools.locator(`a[href="${href}"]`)).toHaveCount(0);
  }
  // One row, and the first document above the tab bar without scrolling.
  const links = await tools.getByRole("link").evaluateAll((as) => as.map((a) => a.getBoundingClientRect().top));
  expect(new Set(links.map(Math.round)).size, "the tools wrap onto more than one row").toBe(1);
  const card = await page.locator('a[href*="/dashboard/documents/"]').first().boundingBox();
  expect(card!.y + 40).toBeLessThanOrEqual(await tabBarTop(page));
  await context.close();
});

test("Historial on a wide screen leaves the tools to the header", async ({ browser }) => {
  const { context, page, userId } = await openAs(browser, "historial-wide", WIDE);
  await insertDocument(userId);
  await page.goto("/es/dashboard/overview");
  await expect(page.getByRole("heading", { level: 1, name: es.dashboard.title })).toBeVisible();
  const tools = page.locator(`nav[aria-label="${es.dashboard.toolsLabel}"]`);
  await expect(tools).toHaveCount(1);
  await expect(tools).toBeHidden();
  // Nothing lost its door: the header names the same five, with labels at this width.
  const header = page.getByRole("navigation", { name: es.dashboard.sectionsLabel });
  for (const path of ["chat", "questionnaire", "briefings", "enrichment", "ingestion"]) {
    await expect(header.locator(`a[href="/es/dashboard/${path}"]`)).toBeVisible();
  }
  // Same names as the row it replaces, in her language.
  await expect(header.locator('a[href="/es/dashboard/briefings"]')).toHaveText(es.briefing.navLabel);
  // Below lg the header shows bare icons, so the labelled row comes back.
  await page.setViewportSize({ width: 900, height: 800 });
  await expect(tools).toBeVisible();
  await context.close();
});

test("Subir is one large button above the fold on a phone", async ({ browser }) => {
  const { context, page } = await openAs(browser, "subir");
  await page.goto("/es/dashboard/upload");
  const button = page.locator("label", { has: page.locator('input[type="file"]') });
  const box = await button.boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(52);
  expect(box!.y + box!.height).toBeLessThanOrEqual(await tabBarTop(page));
  await expect(button).toContainText(es.upload.browse);
  await context.close();
});

test("Modo Consulta leads with the field; recording is the quieter way in", async ({ browser }) => {
  const { context, page } = await openAs(browser, "consulta");
  await page.goto("/es/dashboard/consulta");
  const field = page.getByLabel(es.consulta.emptyPrompt);
  const generate = page.getByRole("button", { name: es.consulta.generate });
  await expect(field).toBeVisible();
  await expect(generate).toBeDisabled();
  await field.fill("El peso está algo bajo");
  await expect(generate).toBeEnabled();
  expect((await generate.boundingBox())!.height).toBeGreaterThanOrEqual(52);
  const record = page.getByRole("link", { name: new RegExp(es.consulta.record.entryTitle) });
  expect((await record.boundingBox())!.y).toBeGreaterThan((await generate.boundingBox())!.y);
  await context.close();
});

test("Grabar: the whole consent row is the target", async ({ browser }) => {
  const { context, page } = await openAs(browser, "grabar");
  await page.goto("/es/dashboard/consulta/grabar");
  const start = page.getByRole("button", { name: es.consulta.record.start });
  await expect(start).toBeDisabled();
  const row = page.locator("label", { has: page.getByRole("checkbox") });
  expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await page.getByText(es.consulta.record.checkboxLabel).click();
  await expect(page.getByRole("checkbox")).toBeChecked();
  await expect(start).toBeEnabled();
  await context.close();
});

test("Ajustes: the email under the title and one heading per setting", async ({ browser }) => {
  const { context, page } = await openAs(browser, "ajustes");
  await page.goto("/es/dashboard/settings");
  await expect(page.getByRole("heading", { level: 1, name: es.settings.title })).toBeVisible();
  for (const name of [es.settings.exportTitle, es.settings.subscriptionTitle, es.settings.languageTitle]) {
    await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  }
  const email = await page.getByText(/@adelia\.test$/).first().boundingBox();
  expect(email!.y).toBeLessThan(220);
  await context.close();
});
