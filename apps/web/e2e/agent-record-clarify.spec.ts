import { expect, test, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import es from "../messages/es.json";
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
  const box = p.getByPlaceholder(es.agent.placeholder);
  await box.fill(text);
  await box.press("Enter");
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
