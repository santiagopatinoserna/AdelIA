import { expect, test, type Browser, type Page } from "@playwright/test";
import { Pool } from "pg";

import es from "../messages/es.json";
import { isoMonthsAgo, seedProfile } from "./utils/seed";
import { seedUserAndSessionCookie } from "./utils/session";

// "Hay demasiadas cosas, no sé dónde leer" (a mother, 2026-11-09) and "la barra
// de conectar a Telegram nunca desaparece" (Santiago). The panel's first screen
// is the conversation: the greeting, "Hoy" when there is something today, the
// record button and the field. Everything else lives once, folded, under
// "Más". Once she asks, nothing competes with the thread. A card she closes is
// remembered by the server for her account. Each answer leads with what to do
// and keeps every warning, "Cuándo ir al médico" and the disclaimer open.
//
// No LLM: the answers are route mocks of POST /agent/turn. The API under test
// runs with a dummy TELEGRAM_BOT_TOKEN, so the Telegram card exists.

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

const MORE = es.panel.more;
const LINK_TELEGRAM = "Diario por Telegram"; // agent/suggestions.py link_title (es)
const plan = es.demo.plan;

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

async function account(tag: string, { child = true } = {}) {
  const { userId, cookie } = await seedUserAndSessionCookie(
    `e2e-panel-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`);
  seeded.push(userId);
  if (child) await seedProfile(userId, { displayName: "Nora", dateOfBirth: isoMonthsAgo(7) });
  return { userId, cookie };
}

async function open(browser: Browser, cookie: Awaited<ReturnType<typeof account>>["cookie"]) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  await context.addCookies([cookie]);
  const page = await context.newPage();
  await page.goto("/es/dashboard");
  await expect(page.getByTestId("agent-canvas")).toBeVisible();
  return { context, page };
}

const more = (page: Page) => page.getByTestId("panel-more");

async function openMore(page: Page) {
  await more(page).locator(":scope > summary").click();
  await expect(more(page)).toHaveAttribute("open", "");
}

// What can be tapped inside the panel (not the shell's top bar and tab bar) and
// is on the first screen.
async function panelControls(page: Page) {
  return page.evaluate(() => {
    const canvas = document.querySelector('[data-testid="agent-canvas"]')!;
    return Array.from(canvas.querySelectorAll<HTMLElement>(
      "a[href], button, textarea, input, summary, [role=button]"))
      .filter((el) => {
        // checkVisibility, not the box: Chrome lays out the content of a closed
        // <details> (content-visibility: hidden), so its box is not empty.
        const r = el.getBoundingClientRect();
        return el.checkVisibility({ visibilityProperty: true, opacityProperty: true }) &&
          r.width > 1 && r.height > 1 && r.top < innerHeight && r.bottom > 0;
      })
      .map((el) => (el.getAttribute("aria-label") || el.innerText).trim().replace(/\s+/g, " "));
  });
}

const sse = (events: [string, unknown][]) =>
  events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");

const evidence = (n: number, extra: Record<string, unknown> = {}) => ({
  tag: `ev_${n}`, source_id: `s${n}`, chunk_id: `c${n}`, title: `Guía de prueba ${n}`,
  organization: "AEP", year: 2024, url: `https://example.org/${n}`, snippet: "Fragmento.", ...extra,
});

const PLAN_ANSWER = [
  "Es frecuente a esta edad y suele mejorar sola [ev_1].",
  "",
  `## ${plan.today}`, "- Tomas más pequeñas y más frecuentes [ev_1].",
  "",
  `## ${plan.watch}`, "- Si deja de ganar peso [ev_2].",
  "",
  `## ${plan.doctor}`, "- Urgencias si vomita verde o con sangre [ev_2].",
  "",
  `## ${plan.remember}`, "- Lleva el registro de tomas a la revisión [ev_1].",
].join("\n");

async function answerWith(page: Page, answer: string, cites: unknown[]) {
  await page.route("**/api/backend/agent/turn", (route) => route.fulfill({
    status: 200, contentType: "text/event-stream",
    body: sse([["start", {}], ["token", { content: answer }],
               ["final", { citations: [], evidence_citations: cites }]]),
  }));
  const box = page.getByTestId("agent-canvas").locator("textarea");
  await box.fill("Regurgita después de cada toma");
  await box.press("Enter");
  await expect(page.locator('[data-role="assistant"] [data-testid="answer-content"]')).toBeVisible();
}

test("the first screen is the conversation; the rest is once, folded, under Más", async ({ browser }) => {
  const { cookie } = await account("first");
  const { context, page } = await open(browser, cookie);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("¿Cómo está Nora?");
  await expect(page.getByTestId("record-consult")).toBeInViewport();
  await expect(page.getByTestId("agent-canvas").locator("textarea")).toBeInViewport();
  // The old showcase and the desktop rail are gone; no suggestion card is drawn
  // in the thread.
  await expect(page.getByTestId("capability-showcase")).toHaveCount(0);
  await expect(page.getByRole("complementary")).toHaveCount(0);
  await expect(page.getByText(LINK_TELEGRAM, { exact: true })).toBeHidden();

  // Few things to tap: record, the example, Más, the field, the mic, send.
  const controls = await panelControls(page);
  expect(controls.length, controls.join(" | ")).toBeLessThanOrEqual(6);

  // Más: closed, one line, and each door once.
  await expect(more(page)).not.toHaveAttribute("open", "");
  await openMore(page);
  for (const name of [es.panel.briefing, es.panel.questionnaire, es.panel.import]) {
    await expect(page.getByRole("link", { name, exact: true }), name).toHaveCount(1);
  }
  await expect(more(page).getByText(LINK_TELEGRAM, { exact: true })).toHaveCount(1);
  await expect(page.getByText(LINK_TELEGRAM, { exact: true })).toHaveCount(1);
  // Not repeated: upload, consult and settings are tabs of the bottom bar.
  await expect(more(page).getByRole("link", { name: /Subir/ })).toHaveCount(0);
  // Every control in Más is a real touch target.
  for (const el of await more(page).locator("a[href], button").all()) {
    const box = (await el.boundingBox())!;
    expect(box.height, await el.innerText()).toBeGreaterThanOrEqual(44 - 0.05);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await context.close();
});

test("a closed Telegram card stays closed after a reload and in another browser", async ({ browser }) => {
  const { cookie } = await account("tg-close");
  const first = await open(browser, cookie);
  await openMore(first.page);
  const card = more(first.page).getByTestId("panel-suggestion").filter({ hasText: LINK_TELEGRAM });
  await expect(card).toHaveCount(1);
  const saved = first.page.waitForResponse((r) =>
    r.url().includes("/agent/suggestions/dismiss") && r.request().method() === "POST");
  await card.getByRole("button", { name: new RegExp(es.panel.dismiss) }).click();
  expect((await saved).status()).toBe(204);
  await expect(first.page.getByText(LINK_TELEGRAM, { exact: true })).toHaveCount(0);

  await first.page.reload();
  await openMore(first.page);
  await expect(first.page.getByText(LINK_TELEGRAM, { exact: true })).toHaveCount(0);
  await first.context.close();

  // Another browser: the memory is the account's, not this one's storage.
  const second = await open(browser, cookie);
  await openMore(second.page);
  await expect(second.page.getByText(LINK_TELEGRAM, { exact: true })).toHaveCount(0);
  // The doors that are not cards are still there.
  await expect(second.page.getByRole("link", { name: es.panel.briefing, exact: true })).toHaveCount(1);
  await second.context.close();
});

test("once Telegram is linked the link offer is gone", async ({ browser }) => {
  const { userId, cookie } = await account("tg-linked");
  const pool = pgPool();
  await pool.query(
    "INSERT INTO telegram_links (user_id, chat_id, username) VALUES ($1, $2, 'e2e_panel')",
    [userId, 100_000_000_000 + Math.floor(Math.random() * 899_999_999_999)]);
  await pool.end();
  const { context, page } = await open(browser, cookie);
  await openMore(page);
  await expect(page.getByText(LINK_TELEGRAM, { exact: true })).toHaveCount(0);
  await context.close();
});

test("a guest with Lucía: no Telegram, the account to keep once, nothing she cannot use", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/es");
  await page.getByTestId("landing-record").click();
  await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar/, { timeout: 30_000 });
  await page.goto("/es/dashboard");
  const id = await page.evaluate(async () =>
    (await fetch("/api/auth/session").then((r) => r.json()))?.user?.id as string | undefined);
  if (id) seeded.push(id);

  await expect(page.getByRole("heading", { level: 1 })).toContainText("Lucía");
  await expect(page.getByTestId("save-account")).toBeHidden();
  await openMore(page);
  await expect(page.getByTestId("save-account")).toHaveCount(1);
  await expect(page.getByTestId("save-account")).toBeVisible();
  await expect(page.getByText(/Telegram/)).toHaveCount(0);
  await expect(page.getByRole("link", { name: es.panel.import, exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: es.panel.questionnaire, exact: true })).toHaveCount(0);
});

test("once she asks, nothing competes with the thread, and the plan keeps every warning open", async ({ browser }) => {
  const { cookie } = await account("thread");
  const { context, page } = await open(browser, cookie);
  await answerWith(page, PLAN_ANSWER, [evidence(1), evidence(2)]);

  // Gone while she reads: the greeting (kept for screen readers only), Más,
  // the example, any suggestion card.
  const h1 = (await page.getByRole("heading", { level: 1 }).boundingBox())!;
  expect(h1.width * h1.height, "the greeting is not painted").toBeLessThanOrEqual(1);
  await expect(more(page)).toHaveCount(0);
  await expect(page.getByTestId("ask-example")).toHaveCount(0);
  await expect(page.getByTestId("panel-suggestion")).toHaveCount(0);
  await expect(page.getByText(LINK_TELEGRAM, { exact: true })).toHaveCount(0);
  // Still at hand: recording the consult and a new conversation.
  await expect(page.getByTestId("record-consult")).toBeVisible();
  await expect(page.getByTestId("new-conversation")).toBeVisible();

  const answer = page.locator('[data-role="assistant"]').last();
  // What to do comes first: the opening, then "Hoy" with nothing between but
  // one jump to "Cuándo ir al médico".
  const map = answer.getByTestId("plan-map");
  await expect(map.getByRole("button")).toHaveText([plan.doctor]);
  const order = await answer.locator("[data-testid^='plan-section-']").evaluateAll(
    (els) => els.map((e) => e.getAttribute("data-testid")));
  expect(order).toEqual(["plan-section-today", "plan-section-watch", "plan-section-doctor",
    "plan-section-remember"]);
  // Fewer icons: the section titles carry none.
  await expect(answer.locator("[data-testid^='plan-section-'] :is(h2, h3) svg")).toHaveCount(0);
  // The contract: nothing clinical is folded, the disclaimer is on screen.
  for (const key of ["today", "watch", "doctor", "remember"]) {
    const section = answer.getByTestId(`plan-section-${key}`);
    await expect(section).toBeVisible();
    expect(await section.evaluate((el) => el.closest("details"))).toBeNull();
  }
  await expect(page.getByTestId("clinical-disclaimer")).toBeVisible();

  // Sources: one quiet line, folded, that still holds every cited card.
  const sources = answer.getByTestId("agent-sources");
  await expect(sources).toHaveCount(1);
  await expect(sources).not.toHaveAttribute("open", "");
  await expect(sources.locator(":scope > summary")).toHaveText(/2/);
  const box = (await sources.locator(":scope > summary").boundingBox())!;
  expect(box.height, "one line, a touch target").toBeLessThanOrEqual(56);
  expect(box.height).toBeGreaterThanOrEqual(44 - 0.05);
  // A marker still leads to its card: the tap opens the line and the card.
  await answer.getByTestId("plan-section-doctor").locator('[data-cite="ev_2"]').click();
  await expect(sources).toHaveAttribute("open", "");
  await expect(sources.locator('[data-cite-target="ev_2"]')).toBeInViewport();
  await context.close();
});

test("a red flag in the panel keeps its source open and leads the answer", async ({ browser }) => {
  const { cookie } = await account("red");
  const { context, page } = await open(browser, cookie);
  const referral = "Llama ahora al 112. No esperes.";
  await answerWith(page, referral, [evidence(1, {
    source_id: "red_flag:seizure", chunk_id: "red_flag:seizure", snippet: "" })]);
  const answer = page.locator('[data-role="assistant"]').last();
  await expect(answer.getByTestId("answer-content")).toHaveText(referral);
  const sources = answer.getByTestId("agent-sources");
  await expect(sources).toHaveAttribute("open", "");
  await expect(sources.getByText("Guía de prueba 1")).toBeVisible();
  await expect(page.getByTestId("clinical-disclaimer")).toBeVisible();
  await context.close();
});
