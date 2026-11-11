import { expect, test, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import es from "../messages/es.json";
import { ask } from "./utils/ask";
import { seedUserAndSessionCookie } from "./utils/session";

// AGENT_GRAPH steps 3-5 on /dashboard: a diary line comes back as a card that
// shows the entry exactly as it will be saved, and nothing is written until
// she says yes; a fever without a reading comes back as one question with
// buttons, and pressing one re-sends her question with the value. The turn
// endpoint is mocked (SSE), so this pins the page, not the API.
test.use({ viewport: { width: 390, height: 844 } });

function sse(events: [string, unknown][]): string {
  return events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}
const final: [string, unknown] = ["final", { citations: [], evidence_citations: [] }];

const recordCard = {
  type: "confirm", id: "rec1", actions: [],
  payload: {
    title: "¿Lo anoto así?", body: "Temperatura: 37,8 °C, hoy a las 17:00",
    tool_name: "registrar_observacion",
    tool_args: { kind: "temperature", value: 37.8, unit: "°C",
                 observed_at: "2026-10-23T17:00:00+02:00", text: "hoy ha tenido 37,8" },
  },
};
const clarifyCard = {
  type: "clarify", id: "clarify-temperature", actions: [],
  payload: {
    field: "temperature", question: "¿Cuánto ha marcado el termómetro?",
    options: [
      { value: "37.5-37.9", label: "37,5 a 37,9 °C" },
      { value: "38-38.9", label: "38 a 38,9 °C" },
      { value: "39+", label: "39 °C o más" },
    ],
    skip: { value: "unknown", label: "No la he medido" },
    message: "Tiene fiebre, ¿qué hago?",
  },
};

async function open(page: Page, browser: import("@playwright/test").Browser, replies: string[]) {
  const bodies: Record<string, unknown>[] = [];
  const { cookie } = await seedUserAndSessionCookie(`e2e-agent-rc-${Date.now()}@adelia.test`);
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await context.addCookies([cookie]);
  const p = await context.newPage();
  await p.route("**/api/backend/agent/turn", (route: Route) => {
    bodies.push(JSON.parse(route.request().postData()!));
    return route.fulfill({ status: 200, contentType: "text/event-stream",
      body: replies[Math.min(bodies.length - 1, replies.length - 1)] });
  });
  await p.goto("/es/dashboard");
  return { p, bodies };
}

async function say(p: Page, text: string) {
  await ask(p.getByPlaceholder(es.agent.placeholder), text);
}

test("es: a diary line shows the entry as it will be saved, and yes sends exactly that", async ({ browser, page }) => {
  const { p, bodies } = await open(page, browser, [
    sse([["start", {}], ["card", { card: recordCard }], final]),
    sse([["start", {}], ["token", { content: "Anotado: 37,8 °C, hoy a las 17:00. La anterior: ayer, 37,2 °C." }], final]),
  ]);
  await say(p, "hoy ha tenido 37,8 a las 5 de la tarde");
  // The canvas renders its card list once per layout; only one is visible.
  const card = p.locator('[data-testid="confirm-card"]:visible');
  await expect(card).toContainText("¿Lo anoto así?");
  await expect(card.getByTestId("confirm-body")).toHaveText("Temperatura: 37,8 °C, hoy a las 17:00");
  for (const name of [es.agent.confirmYes, es.agent.confirmNo]) {
    // Layout height: the entrance animation transforms the box by sub-pixels.
    const h = await card.getByRole("button", { name, exact: true }).evaluate((b) => (b as HTMLElement).offsetHeight);
    expect(h).toBeGreaterThanOrEqual(44);
  }
  await card.getByRole("button", { name: es.agent.confirmYes, exact: true }).click();
  await expect(p.getByText("La anterior: ayer, 37,2 °C.")).toBeVisible();
  expect(bodies[1]).toMatchObject({ card_action: {
    intent: "confirm", tool_name: "registrar_observacion", tool_args: recordCard.payload.tool_args,
  } });
});

test("es: a clarify card asks one question with tall buttons and sends her question with the value", async ({ browser, page }) => {
  const { p, bodies } = await open(page, browser, [
    sse([["start", {}], ["card", { card: clarifyCard }], final]),
    sse([["start", {}], ["token", { content: "Con 39 °C a los 6 meses, que la vea un médico hoy [ev_1]." }], final]),
  ]);
  await say(p, "Tiene fiebre, ¿qué hago?");
  const card = p.locator('[data-testid="clarify-card"]:visible');
  await expect(card.getByRole("heading")).toHaveText("¿Cuánto ha marcado el termómetro?");
  const options = card.getByTestId("clarify-option");
  await expect(options).toHaveText(["37,5 a 37,9 °C", "38 a 38,9 °C", "39 °C o más"]);
  const heights = await card.evaluate((el) =>
    [...el.querySelectorAll('[data-testid="clarify-option"], [data-testid="clarify-skip"]')]
      .map((b) => (b as HTMLElement).offsetHeight));  // layout height: the entrance animation transforms the box
  expect(heights).toHaveLength(4);
  for (const h of heights) expect(h).toBeGreaterThanOrEqual(44);
  for (const colorScheme of ["light", "dark"] as const) {
    await p.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    const audit = await new AxeBuilder({ page: p }).include('[data-testid="clarify-card"]').analyze();
    expect(audit.violations, colorScheme).toEqual([]);
  }
  await options.filter({ hasText: "39 °C o más" }).click();
  await expect(p.getByText("que la vea un médico hoy")).toBeVisible();
  expect(bodies[1]).toMatchObject({
    message: "Tiene fiebre, ¿qué hago?",
    clarification: { field: "temperature", value: "39+" },
  });
  await expect(p.locator('[data-testid="clarify-card"]')).toHaveCount(0);
  expect(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

// 2026-11-09: "si tiene dudas no hace preguntas". A worry about how the baby
// is at the nursery gets one round of two questions before any answer; she
// answers with the buttons, or in her own words in the field below. Either
// way the next turn carries the questions in its history, so the API knows
// her words answer them and never asks a second round.
const GUARDERIA =
  "Mi bebé en la guardería es el único que en tiempo libre se queda sentado en una esquina sin moverse";
const nursery = {
  field: "nursery_time", question: "¿Cuánto lleva yendo a la guardería?",
  options: [
    { value: "lt1m", label: "Menos de un mes" },
    { value: "1-3m", label: "De 1 a 3 meses" },
    { value: "gt3m", label: "Más de 3 meses" },
  ],
  skip: { value: "unknown", label: "No lo sé" },
};
const signals = {
  field: "social_signals",
  question: "En casa y con otros niños, ¿te mira, sonríe, responde a su nombre y balbucea o dice palabras?",
  options: [
    { value: "all", label: "Sí, todo eso" },
    { value: "some_not", label: "Alguna de esas no" },
    { value: "lost", label: "Ha dejado de hacer algo que hacía" },
  ],
  skip: { value: "unknown", label: "No lo sé" },
};
const roundCard = {
  type: "clarify", id: "clarify-nursery_time-social_signals", actions: [],
  payload: {
    ...nursery, questions: [nursery, signals], free: "O escríbemelo con tus palabras.",
    message: GUARDERIA,
  },
};
const asked = `${nursery.question}\n${signals.question}`;

test("es: a two-question card sends her question with both answers, and the questions ride in the history", async ({ browser, page }) => {
  const { p, bodies } = await open(page, browser, [
    sse([["start", {}], ["card", { card: roundCard }], final]),
    sse([["start", {}], ["token", { content: "A las pocas semanas de empezar es la adaptación [ev_1]." }], final]),
  ]);
  await say(p, GUARDERIA);
  const card = p.locator('[data-testid="clarify-card"]:visible');
  await expect(card.getByRole("group")).toHaveCount(2);
  await expect(card).toContainText(nursery.question);
  await expect(card).toContainText(signals.question);
  await expect(card).toContainText("O escríbemelo con tus palabras.");
  const heights = await card.evaluate((el) =>
    [...el.querySelectorAll("button")].map((b) => (b as HTMLElement).offsetHeight));
  expect(heights).toHaveLength(8);
  for (const h of heights) expect(h).toBeGreaterThanOrEqual(44);
  for (const colorScheme of ["light", "dark"] as const) {
    await p.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    const audit = await new AxeBuilder({ page: p }).include('[data-testid="clarify-card"]').analyze();
    expect(audit.violations, colorScheme).toEqual([]);
  }
  await card.getByRole("button", { name: "Menos de un mes" }).click();
  await expect(card.getByRole("button", { name: "Menos de un mes" })).toHaveAttribute("aria-pressed", "true");
  expect(bodies).toHaveLength(1);
  await card.getByRole("button", { name: "Sí, todo eso" }).click();
  await expect(p.getByText("es la adaptación")).toBeVisible();
  expect(bodies[1]).toMatchObject({
    message: GUARDERIA,
    clarifications: [{ field: "nursery_time", value: "lt1m" }, { field: "social_signals", value: "all" }],
    history: [{ role: "user", content: GUARDERIA }, { role: "assistant", content: asked }],
  });
  await expect(p.locator('[data-role="user"]').last()).toHaveText("Menos de un mes · Sí, todo eso");
  await expect(p.locator('[data-testid="clarify-card"]')).toHaveCount(0);
  expect(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("es: answering the card in her own words sends the questions in the history and drops the card", async ({ browser, page }) => {
  const { p, bodies } = await open(page, browser, [
    sse([["start", {}], ["card", { card: roundCard }], final]),
    sse([["start", {}], ["token", { content: "A las pocas semanas de empezar es la adaptación [ev_1]." }], final]),
  ]);
  await say(p, GUARDERIA);
  await expect(p.locator('[data-testid="clarify-card"]:visible')).toBeVisible();
  // After the first turn the field invites a follow-up: found by its label.
  await ask(p.getByLabel(es.agent.inputLabel), "Lleva dos semanas y en casa me mira y se ríe");
  await expect(p.getByText("es la adaptación")).toBeVisible();
  expect(bodies[1]).toMatchObject({
    message: "Lleva dos semanas y en casa me mira y se ríe",
    history: [{ role: "user", content: GUARDERIA }, { role: "assistant", content: asked }],
  });
  expect(bodies[1].clarification).toBeUndefined();
  expect(bodies[1].clarifications).toBeUndefined();
  await expect(p.locator('[data-testid="clarify-card"]')).toHaveCount(0);
});
