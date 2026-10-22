import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";

// Synthetic, non-clinical content: this suite tests reading and disclosure only.
test.use({ viewport: { width: 390, height: 844 } });
const copy = { es, en, fr };
const text = "Una respuesta directa **sin perder condiciones** [ev_1].\n\n- Primera acción documentada [ev_1].\n- Segunda acción, solo si se cumple la condición indicada.\n\n## Cuándo pedir ayuda\n\nEsta advertencia debe permanecer visible, incluso al final de una respuesta larga.";
const citation = {
  tag: "ev_1", source_id: "mother-source", chunk_id: "mother-chunk",
  title: "Título completo de la fuente de prueba", organization: "Institución de prueba",
  year: 2026, url: "https://example.org/source", snippet: "Fragmento literal íntegro para leer con calma.",
};

for (const locale of ["es", "en", "fr"] as const) {
  test(`${locale}: answer first, all clinical content visible, sources for later and a one-tap new question`, async ({ page }) => {
    const m = copy[locale];
    const sent: string[] = [];
    await page.route("**/api/demo/ask", route => {
      sent.push(JSON.parse(route.request().postData()!).question);
      return route.fulfill({ json: {
        kind: "answer", answer: text, evidence_citations: [citation], disclaimer: "Aviso clínico siempre visible.",
      } });
    });
    await page.goto(`/${locale}`);
    await page.locator("#demo-question").fill("Pregunta breve sin redactar perfectamente");
    await page.getByRole("button", { name: m.demo.askCta, exact: true }).click();
    const answer = page.getByTestId("demo-answer");
    await expect(answer).toBeVisible();
    // Do not spend the first phone screen repeating the long question.
    await expect(answer.getByText("Pregunta breve sin redactar perfectamente", { exact: true })).toHaveCount(0);
    await expect(page.locator("#demo-question")).toBeHidden();
    await expect(page.locator('[data-testid="demo-ask"] ul button:visible')).toHaveCount(0);
    const body = page.getByTestId("answer-content");
    // Once she has asked, the invitation to ask must not displace her answer.
    expect((await body.boundingBox())!.y).toBeLessThan(200);
    await expect(body.getByText(/Esta advertencia debe permanecer visible/)).toBeVisible();
    await expect(body.locator("li")).toHaveCount(2);
    await expect(body.locator("details")).toHaveCount(0);
    expect(await body.locator(":scope > p").first().evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(18);
    await expect(answer.getByText("Aviso clínico siempre visible.", { exact: true })).toBeVisible();
    const sources = page.getByTestId("answer-depth");
    await expect(sources).not.toHaveAttribute("open");
    await expect(sources.getByText(citation.title, { exact: true })).toBeHidden();
    const summary = sources.locator(":scope > summary");
    expect((await summary.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await summary.click();
    await expect(sources.getByText(citation.title, { exact: true })).toBeVisible();
    await sources.locator("details > summary").click();
    await expect(sources.locator("blockquote")).toHaveText(citation.snippet);
    const another = page.getByTestId("ask-another");
    expect((await another.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await another.click();
    await expect(page.locator("#demo-question")).toBeFocused();
    await expect(page.locator("#demo-question")).toHaveValue("");
    await expect(page.locator('[data-testid="demo-ask"] ul button:visible')).toHaveCount(3);
    expect(sent).toEqual(["Pregunta breve sin redactar perfectamente"]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("emergency and refusal never fold or shorten the original clinical answer", async ({ page }) => {
  for (const kind of ["red_flag", "no_evidence"]) {
    const original = `Primer párrafo íntegro de ${kind}.\n\nSegundo párrafo con una condición importante.\n\nÚltima advertencia que no debe quedar oculta.`;
    await page.route("**/api/demo/ask", route => route.fulfill({ json: {
      kind, answer: original, evidence_citations: [], disclaimer: "Aviso clínico siempre visible.",
    } }));
    await page.goto("/es");
    await page.locator("#demo-question").fill("Consulta de prueba");
    await page.getByRole("button", { name: "Preguntar", exact: true }).click();
    const content = page.getByTestId("answer-content");
    await expect(content).toBeVisible();
    if (kind === "red_flag") {
      await expect(page.getByTestId("demo-answer").getByRole("heading", { level: 2 })).toHaveText("Esto no puede esperar");
    }
    expect(await content.locator("p").allTextContents()).toEqual(original.split("\n\n"));
    await expect(content.getByText("Última advertencia que no debe quedar oculta.", { exact: true })).toBeVisible();
    await expect(page.getByTestId("answer-depth")).toHaveCount(0);
    const results = await new AxeBuilder({ page }).include('[data-testid="demo-answer"]').analyze();
    expect(results.violations).toEqual([]);
    await page.unroute("**/api/demo/ask");
  }
});

test("a plan answer renders as plan sections, keeps every line, and folds only the sources", async ({ page }) => {
  const plan = es.demo.plan;
  const answer = [
    "Respuesta directa de prueba [ev_1].",
    "",
    `## ${plan.today}`, "- Acción uno [ev_1].", "- Acción dos [2].",
    "", "---", "",
    `## ${plan.watch}`, "- Observación [ev_1].",
    "",
    `## ${plan.doctor}`, "- **Urgencias** si aparece la señal de prueba [ev_1].",
    "",
    `## ${plan.remember}`, "- Indicación previa del pediatra [4].",
    "",
    `## ${plan.mothers}`, "- Lo que contó otra madre [ex_1].",
  ].join("\n");
  await page.route("**/api/demo/ask", (route) => route.fulfill({ json: {
    kind: "answer", answer, evidence_citations: [citation], disclaimer: "Aviso clínico siempre visible.",
  } }));
  await page.goto("/es");
  await page.locator("#demo-question").fill("Pregunta de prueba");
  await page.getByRole("button", { name: "Preguntar", exact: true }).click();
  const body = page.getByTestId("answer-content");
  await expect(body.getByTestId("plan-intro")).toHaveText("Respuesta directa de prueba [ev_1].");
  for (const [key, title] of Object.entries(plan)) {
    const section = body.getByTestId(`plan-section-${key}`);
    await expect(section).toBeVisible();
    await expect(section.getByRole("heading", { level: 3 })).toHaveText(title);
  }
  await expect(body.getByTestId("plan-section-today").locator("li")).toHaveText(["Acción uno [ev_1].", "Acción dos [2]."]);
  await expect(body.getByTestId("plan-section-doctor")).toContainText("Urgencias si aparece la señal de prueba [ev_1].");
  await expect(body.locator("hr")).toHaveCount(0);
  await expect(body.locator("details")).toHaveCount(0);
  await expect(page.getByTestId("answer-depth").locator(":scope > summary")).toContainText(es.demo.readMoreTitle);
  await expect(page.locator("#demo-answer-title")).toHaveText(es.demo.answerTitle);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    const audit = await new AxeBuilder({ page }).include('[data-testid="demo-answer"]').analyze();
    expect(audit.violations, colorScheme).toEqual([]);
  }
});

// What other mothers say (Kenza, 2026-10-22): one optional section after
// "No olvides", labelled as experience, its sources badged and listed after
// the scientific ones. Experience is never clinical: no doses, no warning
// signs, so the section must not look like the doctor card.
test("the mothers section renders last, labelled as experience, and its source is badged and listed after the evidence", async ({ page }) => {
  const plan = es.demo.plan;
  const answer = [
    "Respuesta directa de prueba [ev_1].",
    "",
    `## ${plan.today}`, "- Acción uno [ev_1].",
    "",
    `## ${plan.doctor}`, "- **Urgencias** si aparece la señal de prueba [ev_1].",
    "",
    `## ${plan.remember}`, "- Indicación previa del pediatra [ev_1].",
    "",
    `## ${plan.mothers}`, "- A otras madres les ayudó adelantar la rutina de la noche [ex_1].",
  ].join("\n");
  const experience = {
    tag: "ex_1", source_id: "exp-source", chunk_id: "exp-chunk", tier: "experience",
    title: "Hilo de madres sobre el sueño", organization: "Foro de prueba",
    year: 2026, url: "https://example.org/forum", snippet: "Resumen de lo que cuentan otras madres.",
  };
  // Experience deliberately FIRST in the payload: the page, not the API order,
  // must put it after the scientific sources.
  await page.route("**/api/demo/ask", (route) => route.fulfill({ json: {
    kind: "answer", answer, evidence_citations: [experience, { ...citation, tier: "evidence" }],
    disclaimer: "Aviso clínico siempre visible.",
  } }));
  await page.goto("/es");
  await page.locator("#demo-question").fill("Pregunta de prueba");
  await page.getByRole("button", { name: "Preguntar", exact: true }).click();
  const body = page.getByTestId("answer-content");
  const mothers = body.getByTestId("plan-section-mothers");
  await expect(mothers).toBeVisible();
  await expect(mothers.getByRole("heading", { level: 3 })).toHaveText(plan.mothers);
  await expect(mothers.getByText(es.demo.mothersLabel, { exact: true })).toBeVisible();
  await expect(mothers.locator("li")).toHaveText(["A otras madres les ayudó adelantar la rutina de la noche [ex_1]."]);
  // After "No olvides" and never styled like the doctor card.
  const order = await body.locator("[data-testid^='plan-section-']").evaluateAll(els => els.map(e => e.getAttribute("data-testid")));
  expect(order).toEqual(["plan-section-today", "plan-section-doctor", "plan-section-remember", "plan-section-mothers"]);
  const [doctorBg, mothersBg] = await Promise.all([
    body.getByTestId("plan-section-doctor").evaluate(el => getComputedStyle(el).backgroundColor),
    mothers.evaluate(el => getComputedStyle(el).backgroundColor),
  ]);
  expect(mothersBg).not.toBe(doctorBg);

  const sources = page.getByTestId("answer-depth");
  await sources.locator(":scope > summary").click();
  const cards = sources.locator("[data-testid='evidence-card']");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0)).toContainText(citation.title);
  await expect(cards.nth(1)).toContainText(experience.title);
  await expect(cards.nth(1).getByTestId("experience-badge")).toHaveText(es.demo.experienceBadge);
  await expect(cards.nth(0).getByTestId("experience-badge")).toHaveCount(0);
  await expect(sources.getByText(es.demo.sourcesExperienceTitle, { exact: true })).toBeVisible();

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    const audit = await new AxeBuilder({ page }).include('[data-testid="demo-answer"]').analyze();
    expect(audit.violations, colorScheme).toEqual([]);
  }
});
