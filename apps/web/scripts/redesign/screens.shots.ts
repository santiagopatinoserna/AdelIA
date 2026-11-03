import { test, type Browser, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Pool } from "pg";

import fixtures from "./fixtures.json";
import { isoMonthsAgo, seedDocument, seedProfile } from "../../e2e/utils/seed";
import { seedUserAndSessionCookie } from "../../e2e/utils/session";

// Every screen of the audit, in es/en/fr, at 390x844 light and dark and at
// 1280 light, plus the numbers docs/design/AUDITORIA_UX.md quotes: where the
// first action sits, how many words come before it, what fits in the first
// screen. The answers are fixtures (scripts/redesign/fixtures.json): the plans
// are real outputs of the plan contract (2026-10 probes, 327 to 696 words),
// the red flag and the clarify card are what the local API returns, the rest
// is synthetic. The selectors are the ones the redesign keeps, so the same
// file captures "before" and "after".

// Required: a run without it once wrote the redesign over the "before" set.
const PHASE = process.env.SHOTS_PHASE;
if (!PHASE) throw new Error("SHOTS_PHASE=before|after is required");
const OUT = join(homedir(), "dev/adelia-design/shots/redesign", PHASE);
mkdirSync(join(OUT, "metrics"), { recursive: true });

const LOCALES = ["es", "en", "fr"] as const;
type Locale = (typeof LOCALES)[number];
const VARIANTS = [
  { id: "390-light", width: 390, height: 844, scheme: "light", mobile: true },
  { id: "390-dark", width: 390, height: 844, scheme: "dark", mobile: true },
  { id: "1280-light", width: 1280, height: 800, scheme: "light", mobile: false },
] as const;
type Variant = (typeof VARIANTS)[number];
type Fixture = { question: string; payload: Record<string, unknown> };
const FIX = fixtures as unknown as Record<Locale, Record<string, Fixture>>;

const RECORD: Record<Locale, { title: string; body: string; noted: string }> = {
  es: { title: "¿Lo anoto así?", body: "Temperatura: 37,8 °C, hoy a las 17:00",
        noted: "Anotado: 37,8 °C, hoy a las 17:00. La anterior: ayer, 37,2 °C." },
  en: { title: "Shall I note it like this?", body: "Temperature: 37.8 °C, today at 17:00",
        noted: "Noted: 37.8 °C, today at 17:00. The one before: yesterday, 37.2 °C." },
  fr: { title: "Je le note comme ça ?", body: "Température : 37,8 °C, aujourd’hui à 17 h 00",
        noted: "C’est noté : 37,8 °C, aujourd’hui à 17 h 00. La précédente : hier, 37,2 °C." },
};
const RECORD_TEXT: Record<Locale, string> = {
  es: "hoy ha tenido 37,8", en: "she had 37.8 today", fr: "il a eu 37,8 aujourd’hui",
};

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
  try {
    await pool.query(`DELETE FROM users WHERE id = ANY($1::uuid[])`, [seeded]);
  } finally {
    await pool.end();
  }
});

async function settle(page: Page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(250);
}

async function shoot(page: Page, name: string, full = false) {
  await settle(page);
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  if (full) await page.screenshot({ path: join(OUT, `${name}-full.png`), fullPage: true });
}

// Words a reader meets in the first screen, and the controls she can reach.
async function firstScreen(page: Page) {
  return page.evaluate(() => {
    const vh = innerHeight;
    let words = 0;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const el = n.parentElement;
      if (!el || !n.textContent?.trim()) continue;
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none" || el.closest("[hidden],.sr-only,[aria-hidden=true]")) continue;
      const r = document.createRange();
      r.selectNodeContents(n);
      const rect = r.getBoundingClientRect();
      if (rect.height === 0 || rect.bottom <= 0 || rect.top >= vh) continue;
      words += n.textContent.trim().split(/\s+/).length;
    }
    const controls = [...document.querySelectorAll<HTMLElement>("a[href],button,textarea,input,select,summary")]
      .filter((el) => { const b = el.getBoundingClientRect(); return b.height > 0 && b.top < vh && b.bottom > 0; });
    const small = controls.filter((el) => { const b = el.getBoundingClientRect(); return b.height < 44 || b.width < 44; })
      .map((el) => `${el.tagName.toLowerCase()}:${(el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 30)}`);
    return {
      words, controls: controls.length, smallTargets: small,
      scrollHeight: document.documentElement.scrollHeight,
      sideScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    };
  });
}

// Document position of the first element matching each selector, and the
// words a reader goes through before the first one of `target`.
async function positions(page: Page, selectors: Record<string, string>, target?: string) {
  return page.evaluate(({ selectors, target }) => {
    const out: Record<string, number | null> = {};
    for (const [k, sel] of Object.entries(selectors)) {
      const el = document.querySelector(sel);
      out[k] = el ? Math.round(el.getBoundingClientRect().top + scrollY) : null;
    }
    let wordsBefore: number | null = null;
    const goal = target ? document.querySelector(target) : null;
    if (goal) {
      wordsBefore = 0;
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (goal.contains(n) || (goal.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING)) break;
        const el = n.parentElement;
        if (!el || !n.textContent?.trim()) continue;
        if (el.closest("[hidden],.sr-only,script,style,[aria-hidden=true]")) continue;
        const style = getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden") continue;
        if (el.getBoundingClientRect().height === 0) continue;
        wordsBefore += n.textContent.trim().split(/\s+/).length;
      }
    }
    return { ...out, wordsBefore, viewport: innerHeight };
  }, { selectors, target });
}

async function newPage(browser: Browser, v: Variant) {
  const context = await browser.newContext({
    viewport: { width: v.width, height: v.height },
    isMobile: v.mobile,
    hasTouch: v.mobile,
    colorScheme: v.scheme,
    reducedMotion: "reduce",
    deviceScaleFactor: v.mobile ? 2 : 1,
  });
  return { context, page: await context.newPage() };
}

const ANSWER_SELECTORS = {
  title: "#demo-answer-title",
  firstAction: '[data-testid="plan-section-today"] li, [data-testid="answer-content"] > p:first-child, [data-testid="answer-content"] p',
  today: '[data-testid="plan-section-today"]',
  watch: '[data-testid="plan-section-watch"]',
  doctor: '[data-testid="plan-section-doctor"]',
  remember: '[data-testid="plan-section-remember"]',
  sources: '[data-testid="answer-depth"]',
  askAnother: '[data-testid="ask-another"]',
  disclaimer: '[data-testid="answer-disclaimer"]',
};

async function askDemo(page: Page, locale: Locale, fx: Fixture, delayMs = 0) {
  await page.route("**/api/demo/ask", async (route) => {
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    await route.fulfill({ json: fx.payload }).catch(() => {});
  });
  await page.goto(`/${locale}`);
  await settle(page);
  await page.locator("#demo-question").click();
  await page.locator("#demo-question").fill(fx.question);
  await page.locator('[data-testid="demo-ask"] form [type="submit"]').click();
}

for (const locale of LOCALES) {
  for (const v of VARIANTS) {
    test(`public ${locale} ${v.id}`, async ({ browser }) => {
      const metrics: Record<string, unknown> = {};
      const { context, page } = await newPage(browser, v);
      const p = `${locale}-${v.id}`;

      await page.goto(`/${locale}`);
      await shoot(page, `${p}-01-portada`, true);
      const submit = await page.locator('[data-testid="demo-ask"] form [type="submit"]').boundingBox();
      metrics.portada = { ...(await firstScreen(page)), submitBottom: submit ? Math.round(submit.y + submit.height) : null };

      const record = page.getByTestId("demo-record").locator("summary");
      if (await record.count()) {
        await record.click();
        await record.scrollIntoViewIfNeeded();
        await shoot(page, `${p}-02-historial`);
      }

      for (const [name, key] of [
        ["04-plan", "plan"], ["05-respuesta-corta", "short"], ["06-pregunta-botones", "clarify"],
        ["07-solo-madres", "experience"], ["08-sin-evidencia", "no_evidence"], ["09-urgencia", "red_flag"],
      ] as const) {
        await page.unrouteAll({ behavior: "ignoreErrors" });
        await askDemo(page, locale, FIX[locale][key]);
        await page.locator('[data-testid="demo-answer"], [data-testid="demo-clarify"]').first().waitFor();
        await page.evaluate(() => scrollTo(0, 0));
        await shoot(page, `${p}-${name}`, true);
        metrics[name] = {
          ...(await firstScreen(page)),
          ...(await positions(page, ANSWER_SELECTORS,
            key === "red_flag" ? '[data-testid="answer-content"] p:nth-of-type(3)'
            : key === "clarify" ? '[data-testid="clarify-option"]'
            : key === "plan" ? '[data-testid="plan-section-today"] li'
            : '[data-testid="answer-content"] p')),
          title: await page.locator("#demo-answer-title, #demo-clarify-title").first().textContent(),
        };
        if (key === "plan") {
          const doctor = page.getByTestId("plan-section-doctor");
          await doctor.scrollIntoViewIfNeeded();
          await shoot(page, `${p}-04b-plan-medico`);
          const depth = page.getByTestId("answer-depth");
          if (await depth.count()) {
            await depth.locator(":scope > summary").click();
            await depth.scrollIntoViewIfNeeded();
            await shoot(page, `${p}-04c-plan-fuentes`);
          }
        }
      }

      // Waiting: the request is held until the shot is taken.
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await askDemo(page, locale, FIX[locale].short, 4000);
      await page.waitForTimeout(600);
      await page.screenshot({ path: join(OUT, `${p}-03-espera.png`) });
      await page.unrouteAll({ behavior: "ignoreErrors" });

      // Task tests: the four questions of the brief.
      const tasks: Record<string, unknown> = {};
      // The first element matching a target, in document order, is what she
      // reaches: the map's doctor pill or the call button when the page has
      // them, the section or the paragraph that says it when it does not.
      for (const [task, key, target] of [
        ["regurgita", "plan_reflux", '[data-testid="plan-section-today"] li'],
        ["regurgita-medico", "plan_reflux",
          '[data-testid="plan-map"] button:nth-child(3), [data-testid="plan-section-doctor"]'],
        ["fiebre-2m", "red_flag",
          '[data-testid="call-emergency"], [data-testid="answer-content"] p:nth-of-type(3)'],
        ["gatean", "short", '[data-testid="answer-content"] p'],
      ] as const) {
        await page.unrouteAll({ behavior: "ignoreErrors" });
        const fx = { ...FIX[locale][key], question: FIX[locale][key === "plan_reflux" ? "plan_reflux" : key].question };
        await askDemo(page, locale, fx);
        await page.locator('[data-testid="demo-answer"]').waitFor();
        await page.evaluate(() => scrollTo(0, 0));
        const viaControl = await page.evaluate((sel) => {
          const el = document.querySelector(sel);
          return el ? el.tagName === "BUTTON" || el.tagName === "A" : false;
        }, target);
        tasks[task] = {
          taps: 2, typed: fx.question.length, viaControl,
          ...(await positions(page, { target, doctor: ANSWER_SELECTORS.doctor, title: ANSWER_SELECTORS.title }, target)),
        };
      }
      metrics.tasks = tasks;
      writeFileSync(join(OUT, "metrics", `${p}-public.json`), JSON.stringify(metrics, null, 1));
      await context.close();
    });

    test(`account ${locale} ${v.id}`, async ({ browser }) => {
      const metrics: Record<string, unknown> = {};
      const tag = `${locale}-${v.id}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const { cookie, userId } = await seedUserAndSessionCookie(`redesign-${tag}@adelia.test`);
      seeded.push(userId);
      const profileId = await seedProfile(userId, { displayName: "Nora", dateOfBirth: isoMonthsAgo(3) });
      await seedDocument(userId);
      const pool = pgPool();
      try {
        await pool.query(`UPDATE users SET locale = $2 WHERE id = $1`, [userId, locale]).catch(() => {});
        await pool.query(
          `INSERT INTO observations (user_id, profile_id, kind, value, unit, text, observed_at, source)
           VALUES ($1, $2, 'temperature', 37.2, '°C', 'ha tenido 37,2',
             (((now() AT TIME ZONE 'Europe/Madrid')::date - 1 + time '12:00') AT TIME ZONE 'Europe/Madrid'), 'agent')`,
          [userId, profileId],
        );
        const { rows } = await pool.query(
          `INSERT INTO chat_sessions (id, user_id, title) VALUES (gen_random_uuid(), $1, 'shots') RETURNING id`,
          [userId],
        );
        const remember = { es: "No olvides", en: "Don't forget", fr: "À ne pas oublier" }[locale];
        await pool.query(
          `INSERT INTO chat_messages (id, session_id, user_id, role, content)
           VALUES (gen_random_uuid(), $1, $2, 'assistant', $3)`,
          [rows[0].id, userId, `## ${remember}\n- ${{ es: "Apunta cada toma hasta mañana", en: "Write down every feed until tomorrow", fr: "Notez chaque tétée jusqu’à demain" }[locale]} [ev_2].\n`],
        );
      } finally {
        await pool.end();
      }

      const { context, page } = await newPage(browser, v);
      await context.addCookies([cookie]);
      const p = `${locale}-${v.id}`;

      await page.goto(`/${locale}/dashboard`);
      await page.getByTestId("agent-canvas").waitFor();
      await shoot(page, `${p}-10-inicio`, true);
      metrics.inicio = {
        ...(await firstScreen(page)),
        ...(await positions(page, { today: '[data-testid="today-card"]', input: '[data-testid="agent-canvas"] textarea' })),
      };

      // Log a reading: the confirm card, then the one-line reply.
      const sse = (events: [string, unknown][]) =>
        events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
      const final: [string, unknown] = ["final", { citations: [], evidence_citations: [] }];
      const r = RECORD[locale];
      let turns = 0;
      await page.route("**/api/backend/agent/turn", (route) => {
        turns += 1;
        const body = turns === 1
          ? sse([["start", {}], ["card", { card: { type: "confirm", id: "rec1", actions: [], payload: {
              title: r.title, body: r.body, tool_name: "registrar_observacion",
              tool_args: { kind: "temperature", value: 37.8, unit: "°C" } } } }], final])
          : sse([["start", {}], ["token", { content: r.noted }], final]);
        return route.fulfill({ status: 200, contentType: "text/event-stream", body });
      });
      const box = page.locator('[data-testid="agent-canvas"] textarea');
      await box.click();
      await box.fill(RECORD_TEXT[locale]);
      await box.press("Enter");
      const card = page.locator('[data-testid="confirm-card"]:visible');
      await card.waitFor();
      await shoot(page, `${p}-11-anotar`);
      metrics.anotar = { ...(await firstScreen(page)), ...(await positions(page, { card: '[data-testid="confirm-card"]' })) };
      await card.getByRole("button").first().click();
      await page.getByText(r.noted).first().waitFor();
      await shoot(page, `${p}-11b-anotado`);
      await page.unrouteAll({ behavior: "ignoreErrors" });

      // The agent answering a worry: the same plan the demo renders.
      const plan = FIX[locale].plan_reflux.payload as { answer: string; evidence_citations: unknown[] };
      await page.route("**/api/backend/agent/turn", (route) => route.fulfill({
        status: 200, contentType: "text/event-stream",
        body: sse([["start", {}], ["token", { content: plan.answer }],
                   ["final", { citations: [], evidence_citations: plan.evidence_citations }]]),
      }));
      await box.fill(FIX[locale].plan_reflux.question);
      await box.press("Enter");
      await page.waitForTimeout(1200);
      await shoot(page, `${p}-11c-agente-respuesta`, true);
      metrics.agente = {
        ...(await firstScreen(page)),
        ...(await positions(page, { today: '[data-testid="agent-canvas"] [data-testid="plan-section-today"]',
          doctor: '[data-testid="agent-canvas"] [data-testid="plan-section-doctor"]' })),
      };
      await page.unrouteAll({ behavior: "ignoreErrors" });

      // Chat: empty, then a plan answer streamed from a fixture.
      await page.goto(`/${locale}/dashboard/chat`);
      await shoot(page, `${p}-12-chat`);
      metrics.chat = await firstScreen(page);
      await page.route("**/api/backend/chat", async (route) => {
        if (route.request().method() !== "POST") return route.fallback();
        await route.fulfill({ status: 200, contentType: "text/event-stream", body:
          sse([["start", { session_id: "00000000-0000-0000-0000-000000000001" }],
               ["token", { content: plan.answer }],
               ["final", { session_id: "00000000-0000-0000-0000-000000000001", citations: [],
                 evidence_citations: plan.evidence_citations }]]) });
      });
      const chatBox = page.locator("main textarea").first();
      if (await chatBox.count()) {
        await chatBox.fill(FIX[locale].plan.question);
        await chatBox.press("Enter");
        await page.waitForTimeout(1500);
        await shoot(page, `${p}-12b-chat-respuesta`, true);
      }
      await page.unrouteAll({ behavior: "ignoreErrors" });

      for (const [name, path] of [
        ["13-documentos", "/dashboard/overview"], ["14-subir", "/dashboard/upload"],
        ["15-consulta", "/dashboard/consulta"], ["16-grabar", "/dashboard/consulta/grabar"],
        ["17-ajustes", "/dashboard/settings"],
      ] as const) {
        await page.goto(`/${locale}${path}`);
        await shoot(page, `${p}-${name}`, true);
        metrics[name] = await firstScreen(page);
      }

      // Sign-up and onboarding: signed out, then a fresh account.
      await context.clearCookies();
      await page.goto(`/${locale}/signin`);
      await shoot(page, `${p}-18-alta`);
      metrics.alta = await firstScreen(page);
      const fresh = await seedUserAndSessionCookie(`redesign-onb-${tag}@adelia.test`);
      seeded.push(fresh.userId);
      const pool2 = pgPool();
      await pool2.query("UPDATE users SET onboarded_at = NULL WHERE id = $1", [fresh.userId]);
      await pool2.end();
      await context.addCookies([fresh.cookie]);
      await page.goto(`/${locale}/onboarding`);
      await shoot(page, `${p}-19-onboarding`, true);
      metrics.onboarding = await firstScreen(page);

      writeFileSync(join(OUT, "metrics", `${p}-account.json`), JSON.stringify(metrics, null, 1));
      await context.close();
    });
  }
}
