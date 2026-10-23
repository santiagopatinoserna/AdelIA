import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import es from "../messages/es.json";

// AGENT_GRAPH build step 3: when the answer depends on a fact she did not
// give (the thermometer reading), the demo asks ONE question with two or
// three buttons, and the next turn answers whatever she presses. Buttons are
// at least 44 px tall: she is holding a baby with the other hand.
test.use({ viewport: { width: 390, height: 844 } });

const clarify = {
  kind: "clarify", intent: "clarify", answer: "¿Cuánto ha marcado el termómetro?",
  evidence_citations: [], disclaimer: "Aviso clínico.",
  clarify: {
    field: "temperature", question: "¿Cuánto ha marcado el termómetro?",
    options: [
      { value: "37.5-37.9", label: "37,5 a 37,9 °C" },
      { value: "38-38.9", label: "38 a 38,9 °C" },
      { value: "39+", label: "39 °C o más" },
    ],
    skip: { value: "unknown", label: "No la he medido" },
  },
};
const citation = {
  tag: "ev_1", source_id: "c-source", chunk_id: "c-chunk", title: "Fuente de prueba",
  organization: "Institución", year: 2026, url: "https://example.org/s", snippet: "Fragmento.",
};
const plan = { kind: "answer", intent: "plan", answer: `Respuesta [ev_1].\n\n## ${es.demo.plan.today}\n- Acción [ev_1].`,
  evidence_citations: [citation], disclaimer: "Aviso clínico." };

async function start(page: import("@playwright/test").Page, bodies: unknown[]) {
  await page.route("**/api/demo/ask", (route) => {
    const body = JSON.parse(route.request().postData()!);
    bodies.push(body);
    return route.fulfill({ json: body.clarification ? plan : clarify });
  });
  await page.goto("/es");
  await page.locator("#demo-question").fill("Tiene fiebre, ¿qué hago?");
  await page.getByRole("button", { name: es.demo.askCta, exact: true }).click();
}

test("es: one question, three tall buttons and a way out, nothing else competing", async ({ page }) => {
  const bodies: unknown[] = [];
  await start(page, bodies);
  const box = page.getByTestId("demo-clarify");
  await expect(box.getByRole("heading", { level: 2 })).toHaveText("¿Cuánto ha marcado el termómetro?");
  const options = box.getByTestId("clarify-option");
  await expect(options).toHaveText(["37,5 a 37,9 °C", "38 a 38,9 °C", "39 °C o más"]);
  for (const button of [...await options.all(), box.getByTestId("clarify-skip")]) {
    expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  }
  // A question is not an answer: no sources, no plan, no field to type into.
  await expect(page.getByTestId("demo-answer")).toHaveCount(0);
  await expect(page.locator("#demo-question")).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("es: pressing a value sends the same question with the value and shows the answer", async ({ page }) => {
  const bodies: Record<string, unknown>[] = [];
  await start(page, bodies);
  await page.getByTestId("clarify-option").filter({ hasText: "38 a 38,9 °C" }).click();
  await expect(page.getByTestId("demo-answer")).toBeVisible();
  await expect(page.locator("#demo-answer-title")).toHaveText(es.demo.answerTitle);
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toMatchObject({
    question: "Tiene fiebre, ¿qué hago?",
    clarification: { field: "temperature", value: "38-38.9" },
  });
  await expect(page.getByTestId("demo-clarify")).toHaveCount(0);
});

test("es: the way out still gets an answer", async ({ page }) => {
  const bodies: Record<string, unknown>[] = [];
  await start(page, bodies);
  await page.getByTestId("clarify-skip").click();
  await expect(page.getByTestId("demo-answer")).toBeVisible();
  expect(bodies[1]).toMatchObject({ clarification: { field: "temperature", value: "unknown" } });
});

test("es: the question passes axe in both colour schemes", async ({ page }) => {
  await start(page, []);
  await expect(page.getByTestId("demo-clarify")).toBeVisible();
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    const audit = await new AxeBuilder({ page }).include('[data-testid="demo-clarify"]').analyze();
    expect(audit.violations, colorScheme).toEqual([]);
  }
});
