import { expect, test, type Browser, type BrowserContext, type Locator, type Page } from "@playwright/test";
import { Pool } from "pg";

import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";
import { isoMonthsAgo, seedProfile } from "./utils/seed";
import { seedUserAndSessionCookie } from "./utils/session";

// A question written and sent before the page has hydrated (a slow phone, a
// bad network) must not be lost. Found by the CI review of #72: with the
// page's JavaScript held for 3 s, an Enter in the panel's field went nowhere
// and hydration then emptied the field, with no sign of anything. She thinks
// she asked and nothing happens.
//
// The page's JavaScript is held here behind a gate the test opens itself, so
// "before hydration" is a fact checked on the field (no React props yet), not
// a race against a timer. The agent turn, the demo answer and the chat are
// mocked in the browser: no model, no LLM key. Service workers are blocked
// for the reason usability-findings.spec.ts gives (a worker registered on
// hydration can carry the request past page.route).

const CATALOGS = { es, en, fr } as const;
type Locale = keyof typeof CATALOGS;
const LOCALES = ["es", "en", "fr"] as const;
const QUESTION: Record<Locale, string> = {
  es: "Tiene mocos y tose por la noche, ¿qué hago?",
  en: "She has a runny nose and coughs at night, what do I do?",
  fr: "Elle a le nez qui coule et tousse la nuit, que faire ?",
};
const ANSWER = "Respuesta simulada para la prueba.";

function pgPool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}
const seeded: string[] = [];
test.afterAll(async () => {
  if (!seeded.length) return;
  const pool = pgPool();
  await pool.query("DELETE FROM users WHERE id = ANY($1::uuid[])", [seeded]);
  await pool.end();
});

async function phone(browser: Browser, cookie?: Parameters<BrowserContext["addCookies"]>[0][number]) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: false, hasTouch: true, serviceWorkers: "block",
  });
  if (cookie) await context.addCookies([cookie]);
  return { context, page: await context.newPage() };
}

async function signedIn(browser: Browser, tag: string) {
  const { userId, cookie } = await seedUserAndSessionCookie(
    `e2e-prehydr-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`);
  seeded.push(userId);
  await seedProfile(userId, { displayName: "Lucía", dateOfBirth: isoMonthsAgo(5) });
  return phone(browser, cookie);
}

// Every script chunk waits until the test opens the gate. The HTML, the CSS
// and the inline scripts arrive as usual, so the page is on screen and the
// field takes text: exactly a slow phone before hydration.
async function holdScripts(page: Page) {
  let open!: () => void;
  const gate = new Promise<void>((resolve) => { open = resolve; });
  await page.route("**/_next/static/chunks/**", async (route) => {
    await gate;
    await route.continue().catch(() => {});
  });
  return open;
}

const hydrated = (el: Locator) =>
  el.evaluate((node) => Object.keys(node).some((k) => k.startsWith("__reactProps$")));

const sse = (events: [string, unknown][]) =>
  events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");

// Everything that can carry her question out of the page, counted: the agent
// turn (panel), the keyless demo answer (the landing's fallback) and the chat.
async function countQuestions(page: Page) {
  const sent: string[] = [];
  await page.route("**/api/backend/agent/turn", (route) => {
    sent.push(String(route.request().postDataJSON().message ?? ""));
    return route.fulfill({
      status: 200, contentType: "text/event-stream",
      body: sse([["start", {}], ["token", { content: ANSWER }], ["final", { citations: [], evidence_citations: [] }]]),
    });
  });
  await page.route("**/api/demo/ask", (route) => {
    sent.push(String(route.request().postDataJSON().question ?? ""));
    return route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        kind: "answer", intent: "question", answer: ANSWER, evidence_citations: [], disclaimer: "Aviso.",
      }),
    });
  });
  await page.route("**/api/backend/chat", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    sent.push(String(route.request().postDataJSON().question ?? ""));
    return route.fulfill({ status: 200, contentType: "text/event-stream", body: sse([["token", { content: ANSWER }]]) });
  });
  return sent;
}

// The landing opens a guest space before it asks, and the API brakes guest
// creation at 5 a minute per address: guests minted here would starve the
// specs that need one (qa-traffic, guest-journey) on the same run. The sign-in
// is cut, so the landing answers through its own fallback (/api/demo/ask),
// which is the same ask() the guest path goes through: what is under test is
// the field, not the space.
async function noGuestSpace(page: Page) {
  await page.route("**/api/auth/callback/guest**", (route) => route.abort());
}

// Sent once, and still once a moment later (a late duplicate would come right
// after hydration).
async function expectSentOnce(page: Page, sent: string[], question: string) {
  await expect.poll(() => sent.length, { timeout: 30_000 }).toBe(1);
  expect(sent[0]).toBe(question);
  await page.waitForTimeout(1500);
  expect(sent).toEqual([question]);
}

const panelField = (page: Page) => page.getByTestId("agent-canvas").locator("textarea");
const landingField = (page: Page) => page.locator("#demo-question");

for (const locale of LOCALES) {
  const question = QUESTION[locale];

  test(`${locale}: an Enter in the panel before hydration is sent once, after it`, async ({ browser }) => {
    const { context, page } = await signedIn(browser, `panel-${locale}`);
    const sent = await countQuestions(page);
    const open = await holdScripts(page);
    await page.goto(`/${locale}/dashboard`, { waitUntil: "commit" });
    const field = panelField(page);
    await expect(field).toBeVisible();
    expect(await hydrated(field), "the field must still be server HTML").toBe(false);
    await field.fill(question);
    await field.press("Enter");
    // Nothing is lost while she waits, and the field says it is on its way.
    await expect(field).toHaveValue(question);
    await expect(field).toHaveAttribute("aria-busy", "true");
    expect(sent).toEqual([]);

    open();
    await expectSentOnce(page, sent, question);
    await expect(page.getByTestId("agent-message").filter({ hasText: question })).toHaveCount(1);
    await expect(page.locator('[data-role="assistant"]').last()).toContainText(ANSWER);
    await expect(field).toHaveValue("");
    await expect(field).not.toHaveAttribute("aria-busy", "true");
    await context.close();
  });

  test(`${locale}: an Enter on the landing before hydration is sent once, after it`, async ({ browser }) => {
    const { context, page } = await phone(browser);
    await noGuestSpace(page);
    const sent = await countQuestions(page);
    const open = await holdScripts(page);
    await page.goto(`/${locale}`, { waitUntil: "commit" });
    const field = landingField(page);
    await expect(field).toBeVisible();
    expect(await hydrated(field), "the field must still be server HTML").toBe(false);
    await field.fill(question);
    await field.press("Enter");
    await expect(field).toHaveValue(question);
    await expect(field).toHaveAttribute("aria-busy", "true");
    expect(page.url()).not.toContain("?");

    open();
    await expectSentOnce(page, sent, question);
    await expect(page.getByTestId("demo-answer")).toContainText(ANSWER);
    await context.close();
  });

  test(`${locale}: without any delay the panel sends as before`, async ({ browser }) => {
    const { context, page } = await signedIn(browser, `panel-now-${locale}`);
    const sent = await countQuestions(page);
    await page.goto(`/${locale}/dashboard`);
    const field = panelField(page);
    await expect.poll(() => hydrated(field)).toBe(true);
    await field.fill(question);
    await field.press("Enter");
    await expectSentOnce(page, sent, question);
    await expect(field).toHaveValue("");
    await context.close();
  });
}

test("es: without any delay the landing sends as before", async ({ browser }) => {
  const { context, page } = await phone(browser);
  await noGuestSpace(page);
  const sent = await countQuestions(page);
  await page.goto("/es");
  const field = landingField(page);
  await expect.poll(() => hydrated(field)).toBe(true);
  await field.fill(QUESTION.es);
  await field.press("Enter");
  await expectSentOnce(page, sent, QUESTION.es);
  await context.close();
});

test("es: text written before hydration and not sent stays in the panel's field, unsent", async ({ browser }) => {
  const { context, page } = await signedIn(browser, "panel-kept");
  const sent = await countQuestions(page);
  const open = await holdScripts(page);
  await page.goto("/es/dashboard", { waitUntil: "commit" });
  const field = panelField(page);
  await expect(field).toBeVisible();
  expect(await hydrated(field)).toBe(false);
  await field.fill(QUESTION.es);

  open();
  await expect.poll(() => hydrated(field)).toBe(true);
  // A render after hydration (the mic check, the suggestions) used to put
  // the empty server value back.
  await page.waitForTimeout(1500);
  await expect(field).toHaveValue(QUESTION.es);
  expect(sent).toEqual([]);
  const send = page.getByRole("button", { name: es.agent.send });
  await expect(send).toBeEnabled();
  await field.press("Enter");
  await expectSentOnce(page, sent, QUESTION.es);
  await context.close();
});

test("es: the send button tapped before hydration sends once, after it", async ({ browser }) => {
  const { context, page } = await signedIn(browser, "panel-button");
  const sent = await countQuestions(page);
  const open = await holdScripts(page);
  await page.goto("/es/dashboard", { waitUntil: "commit" });
  const field = panelField(page);
  await expect(field).toBeVisible();
  expect(await hydrated(field)).toBe(false);
  await field.fill(QUESTION.es);
  await page.getByRole("button", { name: es.agent.send }).click();
  await expect(field).toHaveValue(QUESTION.es);
  await expect(field).toHaveAttribute("aria-busy", "true");

  open();
  await expectSentOnce(page, sent, QUESTION.es);
  await expect(field).toHaveValue("");
  await context.close();
});

test("es: the landing's button tapped before hydration sends once and never reloads the page", async ({ browser }) => {
  const { context, page } = await phone(browser);
  await noGuestSpace(page);
  const sent = await countQuestions(page);
  const open = await holdScripts(page);
  await page.goto("/es", { waitUntil: "commit" });
  const field = landingField(page);
  await expect(field).toBeVisible();
  expect(await hydrated(field)).toBe(false);
  await field.fill(QUESTION.es);
  await page.getByRole("button", { name: es.demo.askCta, exact: true }).click();
  await expect(field).toHaveValue(QUESTION.es);
  expect(page.url()).not.toContain("?");

  open();
  await expectSentOnce(page, sent, QUESTION.es);
  await context.close();
});

test("es: an Enter in the chat before hydration is sent once, after it", async ({ browser }) => {
  const { context, page } = await signedIn(browser, "chat");
  const sent = await countQuestions(page);
  const open = await holdScripts(page);
  await page.goto("/es/dashboard/chat", { waitUntil: "commit" });
  const field = page.getByRole("textbox", { name: es.chat.placeholder });
  await expect(field).toBeVisible();
  expect(await hydrated(field)).toBe(false);
  await field.fill(QUESTION.es);
  await field.press("Enter");
  await expect(field).toHaveValue(QUESTION.es);

  open();
  await expectSentOnce(page, sent, QUESTION.es);
  await expect(field).toHaveValue("");
  await context.close();
});
