import { test, type Browser, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Pool } from "pg";

import fixtures from "./fixtures.json";
import { CONSENT_VERSION } from "../../lib/analytics";
import { isoMonthsAgo, seedProfile } from "../../e2e/utils/seed";
import { seedUserAndSessionCookie } from "../../e2e/utils/session";

// "Hay demasiadas cosas, no sé dónde leer" (a mother, 2026-11-09). The panel
// cleanup is measured, not described: for each first screen at 390x844 this
// counts what she can tap and what she has to read, and keeps the screenshot.
//
//   SHOTS_PHASE=before|after pnpm exec playwright test \
//     -c scripts/redesign/shots.config.ts panel.shots.ts
//
// Screens: a guest with Lucía (the landing's way in), an account with no
// conversation, the same account after a plan answer (first screen, then the
// whole answer). Light and dark. The plan is the fixture the redesign shots
// already use (a real output of the plan contract), streamed by a route mock.
const PHASE = process.env.SHOTS_PHASE;
if (!PHASE) throw new Error("SHOTS_PHASE=before|after is required");
const OUT = join(homedir(), "dev/adelia-design/shots/panel-clean", PHASE);
mkdirSync(OUT, { recursive: true });

type Fixture = { question: string; payload: { answer: string; evidence_citations: unknown[] } };
const PLAN = (fixtures as unknown as Record<string, Record<string, Fixture>>).es.plan_reflux;

const SCHEMES = ["light", "dark"] as const;

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

async function phone(browser: Browser, scheme: "light" | "dark") {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
    colorScheme: scheme, locale: "es-ES",
  });
  // The analytics banner is its own screen state; answer it as a mother would.
  await context.addInitScript((v) => {
    try {
      localStorage.setItem("adelia-analytics-consent",
        JSON.stringify({ choice: "rejected", v, at: Date.now() }));
    } catch { /* blocked */ }
  }, CONSENT_VERSION);
  return { context, page: await context.newPage() };
}

// What the first screen asks of her: everything she could tap, every block of
// text she could read, the words, the headings and the icons, inside 390x844.
// The shell (top bar and tab bar) is counted apart: it is the same on every
// screen, and the complaint is about the panel.
async function firstScreen(page: Page) {
  return page.evaluate(() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const shell = (el: Element) => Boolean(el.closest("body > div header.sticky, nav.fixed"));
    const painted = (el: Element) => {
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return false;
      if (r.bottom <= 0 || r.top >= vh || r.right <= 0 || r.left >= vw) return false;
      // checkVisibility: Chrome lays out the content of a closed <details>.
      return el.checkVisibility({ visibilityProperty: true, opacityProperty: true }) &&
        !el.closest("[hidden], .sr-only");
    };
    // Icons are aria-hidden on purpose; everything else hidden from her is not counted.
    const visible = (el: Element) => painted(el) && !el.closest("[aria-hidden='true']");
    const interactive = Array.from(document.querySelectorAll(
      "a[href], button, input:not([type=hidden]), textarea, select, summary, [role=button], [tabindex='0']",
    )).filter(visible);
    const texts = Array.from(document.querySelectorAll("h1, h2, h3, h4, h5, p, li, label, summary"))
      .filter(visible)
      .filter((el) => (el as HTMLElement).innerText.trim().length > 0)
      // a block inside another counted block is the same block
      .filter((el, _i, all) => !all.some((o) => o !== el && o.contains(el)));
    const icons = Array.from(document.querySelectorAll("svg")).filter(painted);
    const words = (els: Element[]) =>
      els.reduce((n, el) => n + (el as HTMLElement).innerText.trim().split(/\s+/).filter(Boolean).length, 0);
    const panel = <T extends Element>(els: T[]) => els.filter((el) => !shell(el));
    return {
      interactive: panel(interactive).length,
      interactiveWithShell: interactive.length,
      textBlocks: panel(texts).length,
      words: words(panel(texts)),
      headings: panel(texts).filter((el) => /^H\d$/.test(el.tagName)).length,
      icons: panel(icons).length,
      labels: panel(interactive).map((el) =>
        ((el as HTMLElement).getAttribute("aria-label") || (el as HTMLElement).innerText || el.tagName)
          .trim().replace(/\s+/g, " ").slice(0, 40)),
    };
  });
}

// The answer, whole: what it is made of, whatever fits on the screen.
async function answerAnatomy(page: Page) {
  return page.evaluate(() => {
    const msg = Array.from(document.querySelectorAll('[data-role="assistant"]')).pop();
    if (!msg) return null;
    const shown = (el: Element) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 &&
        el.checkVisibility({ visibilityProperty: true, opacityProperty: true });
    };
    const all = (sel: string) => Array.from(msg.querySelectorAll(sel)).filter(shown);
    const firstAt = (sel: string) => {
      const el = msg.querySelector(sel);
      return el ? Math.round(el.getBoundingClientRect().top + window.scrollY) : null;
    };
    return {
      headings: all("h2, h3, h4, h5").length,
      listItems: all("li").length,
      icons: all("svg").length,
      interactive: all("a[href], button, summary, [role=button]").length,
      sourceCardsOpen: all("[data-cite-target]").length,
      height: Math.round(msg.getBoundingClientRect().height),
      todayTop: firstAt('[data-testid="plan-section-today"]'),
      doctorTop: firstAt('[data-testid="plan-section-doctor"]'),
      words: (msg as HTMLElement).innerText.trim().split(/\s+/).length,
    };
  });
}

const sse = (events: [string, unknown][]) =>
  events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");

async function settle(page: Page) {
  await page.getByTestId("agent-canvas").waitFor();
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(600);
}

for (const scheme of SCHEMES) {
  test(`panel, guest with Lucía (${scheme})`, async ({ browser }) => {
    const { context, page } = await phone(browser, scheme);
    await page.goto("/es");
    await page.getByTestId("landing-record").click();
    await page.waitForURL(/\/dashboard\/consulta\/grabar/, { timeout: 30_000 });
    await page.goto("/es/dashboard");
    await settle(page);
    await page.screenshot({ path: join(OUT, `guest-lucia-390-${scheme}.png`) });
    const metrics = await firstScreen(page);
    writeFileSync(join(OUT, `guest-lucia-${scheme}.json`), JSON.stringify(metrics, null, 1));
    // Erase the guest the way she would (GDPR art. 17): a guest row is an account.
    const id = await page.evaluate(async () => {
      const s = await fetch("/api/auth/session").then((r) => r.json());
      return s?.user?.id as string | undefined;
    });
    if (id) seeded.push(id);
    await context.close();
  });

  test(`panel, account without and with a conversation (${scheme})`, async ({ browser }) => {
    const { userId, cookie } = await seedUserAndSessionCookie(
      `panel-clean-${scheme}-${Date.now()}@adelia.test`);
    seeded.push(userId);
    await seedProfile(userId, { displayName: "Nora", dateOfBirth: isoMonthsAgo(7) });
    const { context, page } = await phone(browser, scheme);
    await context.addCookies([cookie]);
    await page.goto("/es/dashboard");
    await settle(page);
    await page.screenshot({ path: join(OUT, `account-empty-390-${scheme}.png`) });
    writeFileSync(join(OUT, `account-empty-${scheme}.json`),
      JSON.stringify(await firstScreen(page), null, 1));

    await page.route("**/api/backend/agent/turn", (route) => route.fulfill({
      status: 200, contentType: "text/event-stream",
      body: sse([["start", {}], ["token", { content: PLAN.payload.answer }],
                 ["final", { citations: [], evidence_citations: PLAN.payload.evidence_citations }]]),
    }));
    const box = page.locator('[data-testid="agent-canvas"] textarea');
    await box.fill(PLAN.question);
    await box.press("Enter");
    await page.locator('[data-role="assistant"] [data-testid="answer-content"]').waitFor();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: join(OUT, `account-answer-390-${scheme}.png`) });
    const first = await firstScreen(page);
    const anatomy = await answerAnatomy(page);
    // The whole answer, as one tall picture of the scrolling thread.
    const thread = page.locator('[data-testid="agent-canvas"] main > div').first();
    const full = await thread.evaluate((el) => el.scrollHeight);
    await page.setViewportSize({ width: 390, height: Math.min(full + 300, 12_000) });
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(OUT, `account-answer-full-390-${scheme}.png`) });
    writeFileSync(join(OUT, `account-answer-${scheme}.json`),
      JSON.stringify({ firstScreen: first, answer: anatomy }, null, 1));
    await context.close();
  });
}
