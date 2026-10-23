import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";

// AGENT_GRAPH build step 2: the route node picks the contract. A question that
// asks for a fact ("¿es normal que...?") gets one sentence and a few cited
// bullets, and the page must not call that a plan. Synthetic content only.
test.use({ viewport: { width: 390, height: 844 } });
const copy = { es, en, fr };
const citation = {
  tag: "ev_1", source_id: "shape-source", chunk_id: "shape-chunk",
  title: "Título de la fuente de prueba", organization: "Institución de prueba",
  year: 2026, url: "https://example.org/source", snippet: "Fragmento de prueba.",
};
const shortAnswer = "Sí, es frecuente a esta edad [ev_1].\n\n- Suele mejorar antes del año [ev_1].\n- Consulta hoy si vomita con fuerza [ev_1].";

async function ask(page: import("@playwright/test").Page, locale: "es" | "en" | "fr", intent: string, answer: string) {
  await page.route("**/api/demo/ask", (route) => route.fulfill({ json: {
    kind: "answer", intent, answer, evidence_citations: [citation], disclaimer: "Aviso clínico.",
  } }));
  await page.goto(`/${locale}`);
  await page.locator("#demo-question").fill("Pregunta de prueba");
  await page.getByRole("button", { name: copy[locale].demo.askCta, exact: true }).click();
  await expect(page.getByTestId("demo-answer")).toBeVisible();
}

for (const locale of ["es", "en", "fr"] as const) {
  test(`${locale}: a fact question is titled as an answer, never as a plan`, async ({ page }) => {
    const m = copy[locale].demo;
    await ask(page, locale, "question", shortAnswer);
    await expect(page.locator("#demo-answer-title")).toHaveText(m.shortAnswerTitle);
    await expect(page.locator("#demo-answer-title")).not.toHaveText(m.answerTitle);
    const body = page.getByTestId("answer-content");
    await expect(body.getByText(/Consulta hoy si vomita con fuerza/)).toBeVisible();
    await expect(body.locator('[data-testid^="plan-section-"]')).toHaveCount(0);
    await expect(page.getByTestId("answer-depth").locator(":scope > summary"))
      .toContainText(m.readMoreTitleAnswer);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });

  test(`${locale}: a plan keeps the plan title`, async ({ page }) => {
    const m = copy[locale].demo;
    await ask(page, locale, "plan", `Respuesta [ev_1].\n\n## ${m.plan.today}\n- Acción [ev_1].`);
    await expect(page.locator("#demo-answer-title")).toHaveText(m.answerTitle);
    await expect(page.getByTestId("answer-depth").locator(":scope > summary"))
      .toContainText(m.readMoreTitle);
  });
}

test("es: an answer without intent (older API) is still titled as a plan", async ({ page }) => {
  await page.route("**/api/demo/ask", (route) => route.fulfill({ json: {
    kind: "answer", answer: "Respuesta [ev_1].", evidence_citations: [citation], disclaimer: "Aviso clínico.",
  } }));
  await page.goto("/es");
  await page.locator("#demo-question").fill("Pregunta de prueba");
  await page.getByRole("button", { name: es.demo.askCta, exact: true }).click();
  await expect(page.locator("#demo-answer-title")).toHaveText(es.demo.answerTitle);
});

test("es: the short answer passes axe in both colour schemes", async ({ page }) => {
  await ask(page, "es", "question", shortAnswer);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    const audit = await new AxeBuilder({ page }).include('[data-testid="demo-answer"]').analyze();
    expect(audit.violations, colorScheme).toEqual([]);
  }
});
