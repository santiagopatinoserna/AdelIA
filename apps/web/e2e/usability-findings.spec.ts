import { expect, test, type Browser, type BrowserContextOptions, type Page } from "@playwright/test";
import { Pool } from "pg";

import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";
import fixtures from "../e2e-prod/usability/fixtures.json";
import { smallTargets } from "../e2e-prod/usability/kit";
import { coveredControls, tapTargets } from "../e2e-prod/usability/page";
import { isoMonthsAgo, seedProfile } from "./utils/seed";
import { seedUserAndSessionCookie } from "./utils/session";

// What the usability battery (e2e-prod/usability) found on production on
// 2026-11-11, pinned here so CI fails if it comes back. The battery measures
// production and is not part of CI; these checks use the same probes
// (tapTargets, coveredControls, smallTargets) against the local stack, with
// the agent turn mocked in the browser: no model, no LLM key.
//
//  1. The panel's urgency had no button to call: «Llama al 112» was text.
//  2. At 360 px the two-question clarify card ran under the fold.
//  3. Targets under 44 px: the tablet header's section icons (28x28) and
//     «Ver todo» (18 px tall), the landing footer's links at 360 and the
//     banner's «Detalles» (42.6 px).
//  4. The cookie banner covered the landing's example questions until she
//     answered it.
//  5. «Nueva conversación» wrapped to a second row at 360 (and 390 in
//     French), the French follow-up hint was cut at 360, and the empty panel
//     of a tablet opened with about 250 px of blank above the greeting.

const CATALOGS = { es, en, fr } as const;
type Locale = keyof typeof CATALOGS;
const LOCALES = ["es", "en", "fr"] as const;
const PHONE = (width: number, height = 844): BrowserContextOptions => ({
  // As the usability battery opens a phone (page.ts openContext): desktop
  // Chrome at a phone's width, so a classic scrollbar takes its width too.
  viewport: { width, height }, isMobile: false, hasTouch: true,
});
const TABLET: BrowserContextOptions = { viewport: { width: 768, height: 1024 }, hasTouch: true };

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

async function panel(browser: Browser, tag: string, locale: Locale, options: BrowserContextOptions) {
  const { userId, cookie } = await seedUserAndSessionCookie(
    `e2e-usab-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`);
  seeded.push(userId);
  await seedProfile(userId, { displayName: "Lucía", dateOfBirth: isoMonthsAgo(5) });
  const context = await browser.newContext(options);
  await context.addCookies([cookie]);
  const page = await context.newPage();
  await page.goto(`/${locale}/dashboard`);
  await expect(page.getByTestId("agent-canvas")).toBeVisible();
  return { context, page };
}

const sse = (events: [string, unknown][]) =>
  events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");

async function mockTurns(page: Page, bodies: string[]) {
  const sent: Record<string, unknown>[] = [];
  await page.route("**/api/backend/agent/turn", (route) => {
    sent.push(route.request().postDataJSON());
    return route.fulfill({
      status: 200, contentType: "text/event-stream", body: bodies[Math.min(sent.length - 1, bodies.length - 1)],
    });
  });
  return sent;
}

async function say(page: Page, text: string) {
  const field = page.getByTestId("agent-canvas").locator("textarea");
  await field.fill(text);
  await field.press("Enter");
}

// --- 1. the urgency calls in one tap ------------------------------------------

// The fixed frame of answer_contract.red_flag_reply, as the guard sends it: the
// web reads the number from this frame only, never from a model's text.
const RED_FLAG_REPLY: Record<Locale, string> = {
  es: "Esto no puede esperar a una respuesta mía.\n\nHas descrito un color azulado en los labios.\n\n" +
    "Llama al 112 o acude ahora a urgencias pediátricas, y cuéntales exactamente lo que acabas de " +
    "escribirme.\n\nNo voy a valorar esto a distancia.",
  en: "This cannot wait for an answer from me.\n\nYou described blue lips.\n\n" +
    "Call 112 or go to a paediatric emergency department now, and tell them exactly what you just " +
    "wrote to me.\n\nI am not going to assess this remotely.",
  fr: "Cela ne peut pas attendre une réponse de ma part.\n\nVous décrivez des lèvres bleues.\n\n" +
    "Appelez le 112 ou rendez-vous maintenant aux urgences pédiatriques, et dites-leur exactement ce " +
    "que vous venez de m’écrire.\n\nJe ne vais pas évaluer cela à distance.",
};
const RED_FLAG_SOURCE = {
  tag: "ev_1", source_id: "red_flag:cyanosis", chunk_id: "red_flag:cyanosis",
  title: "Guía de prueba", organization: "AEP", year: 2024, url: "https://example.org/1", snippet: "",
};

for (const locale of LOCALES) {
  test(`1.${locale} the panel's urgency opens with a big button that calls 112`, async ({ browser }) => {
    const { context, page } = await panel(browser, `urgent-${locale}`, locale, PHONE(390));
    await mockTurns(page, [sse([["start", {}], ["token", { content: RED_FLAG_REPLY[locale] }],
      ["final", { citations: [], evidence_citations: [RED_FLAG_SOURCE] }]])]);
    await say(page, "tiene los labios morados");
    const answer = page.locator('[data-role="assistant"]').last();
    const call = answer.getByTestId("call-emergency");
    await expect(call).toHaveAttribute("href", "tel:112");
    await expect(call).toHaveText(CATALOGS[locale].demo.callEmergency.replace("{number}", "112"));
    // The first and strongest thing of the answer, on screen as it arrives.
    await expect(call).toBeInViewport({ ratio: 1 });
    const c = (await call.boundingBox())!;
    const text = (await answer.getByTestId("answer-content").boundingBox())!;
    expect(c.y + c.height, "the call sits above the text").toBeLessThanOrEqual(text.y + 0.5);
    expect(c.height, "the screen's main action, 52 px").toBeGreaterThanOrEqual(52 - 0.05);
    expect(c.width, "the width of the answer").toBeGreaterThanOrEqual(text.width * 0.9);
    // Nothing of the card is gone: the code's reply follows, whole.
    await expect(answer.getByTestId("answer-content")).toHaveText(
      RED_FLAG_REPLY[locale].replace(/\n+/g, " "));
    await expect(page.getByTestId("clinical-disclaimer")).toBeVisible();
    await context.close();
  });
}

test("1. a 112 inside a model's plan is not a call button", async ({ browser }) => {
  const { context, page } = await panel(browser, "urgent-plan", "es", PHONE(390));
  const planText = `Suele mejorar sola [ev_1].\n\n## ${es.demo.plan.doctor}\n- Llama al 112 si no respira [ev_1].`;
  await mockTurns(page, [sse([["start", {}], ["token", { content: planText }],
    ["final", { citations: [], evidence_citations: [{ ...RED_FLAG_SOURCE, source_id: "s1", chunk_id: "c1" }] }]])]);
  await say(page, "regurgita");
  await expect(page.getByTestId("plan-section-doctor")).toBeVisible();
  await expect(page.getByTestId("call-emergency")).toHaveCount(0);
  await context.close();
});

// --- 2. the clarify card fits a 360 px phone (and a 390 one) -----------------------------------

for (const [width, height] of [[360, 780], [390, 844]] as const) {
for (const locale of LOCALES) {
  for (const scheme of ["light", "dark"] as const) {
    test(`2.${locale}.${scheme}.${width} the two-question card fits whole at ${width}x${height}, under the thumb`, async ({ browser }) => {
      const { context, page } = await panel(browser, `clarify-${locale}-${scheme}-${width}`, locale,
        { ...PHONE(width, height), colorScheme: scheme });
      const f = fixtures.clarify[locale];
      const sent = await mockTurns(page, [
        sse([["start", {}], ["card", { card: f.card }], ["final", { citations: [], evidence_citations: [] }]]),
        sse([["start", {}], ["token", { content: "Gracias." }], ["final", { citations: [], evidence_citations: [] }]]),
      ]);
      await say(page, f.message);
      const card = page.getByTestId("clarify-card");
      await expect(card).toBeVisible();
      await page.waitForTimeout(700); // the entrance animation
      // Every button and «O escríbemelo» inside the part of the thread she sees.
      const fit = await card.evaluate((el) => {
        const scroller = el.closest(".overflow-y-auto")!.getBoundingClientRect();
        const top = Math.max(0, scroller.top);
        const bottom = Math.min(innerHeight, scroller.bottom);
        const cw = el.getBoundingClientRect().width;
        const items = [...el.querySelectorAll("button, p")].map((b) => {
          const r = b.getBoundingClientRect();
          return { label: (b as HTMLElement).innerText.trim(), tag: b.tagName, top: r.top, bottom: r.bottom,
            height: r.height, width: r.width, option: b.getAttribute("data-testid") === "clarify-option" };
        });
        return { top, bottom, cw, vh: innerHeight, items };
      });
      const hidden = fit.items.filter((i) => i.top < fit.top - 0.5 || i.bottom > fit.bottom + 0.5);
      expect(hidden.map((i) => `${i.label} ${Math.round(i.top)}-${Math.round(i.bottom)} of ${Math.round(fit.top)}-${Math.round(fit.bottom)}`),
        "under the fold").toEqual([]);
      for (const b of fit.items.filter((i) => i.tag === "BUTTON")) {
        expect(b.height, `${b.label} height`).toBeGreaterThanOrEqual(44 - 0.05);
        expect((b.top + b.bottom) / 2, `${b.label} out of the thumb's reach`).toBeGreaterThan(fit.vh * 0.25);
        if (b.option) expect(b.width, `${b.label} width`).toBeGreaterThanOrEqual(fit.cw * 0.6);
      }
      expect(fit.items.at(-1)!.label).toBe(f.card.payload.free);
      // Two taps, one turn with both answers.
      const groups = card.getByRole("group");
      await groups.nth(0).getByTestId("clarify-option").first().click();
      await groups.nth(1).getByTestId("clarify-option").first().click();
      await expect(page.getByText("Gracias.")).toBeVisible();
      expect(sent).toHaveLength(2);
      expect((sent[1].clarifications as unknown[]).length).toBe(2);
      await context.close();
    });
  }
}
}

// --- 3. 44 px targets -----------------------------------------------------------

test("3. tablet: the header's section icons and «Ver todo» are 44 px targets", async ({ browser }) => {
  const { context, page } = await panel(browser, "tablet-targets", "es", TABLET);
  const small = smallTargets(await tapTargets(page)).map((t) => `${t.name} ${t.width.toFixed(1)}x${t.height.toFixed(1)}`);
  expect(small).toEqual([]);
  // Every section icon still in the header, none scrolled out of it.
  const nav = page.getByRole("navigation", { name: es.dashboard.sectionsLabel });
  const clipped = await nav.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(clipped, "section icons hidden behind the header's edge").toBeLessThanOrEqual(1);
  await context.close();
});

for (const locale of LOCALES) {
  test(`3.${locale} landing at 360: the footer's links and «${CATALOGS[locale].consent.bannerMore}» are 44 px`, async ({ browser }) => {
    const context = await browser.newContext(PHONE(360, 780));
    const page = await context.newPage();
    await page.goto(`/${locale}`);
    await expect(page.getByTestId("consent-banner")).toBeVisible();
    const small = smallTargets(await tapTargets(page)).map((t) => `${t.name} ${t.width.toFixed(1)}x${t.height.toFixed(1)}`);
    expect(small).toEqual([]);
    await context.close();
  });
}

// --- 4. the banner covers nothing --------------------------------------------

for (const locale of LOCALES) {
  for (const width of [360, 390, 430, 768]) {
    test(`4.${locale}.${width} the cookie banner covers none of the landing until she answers`, async ({ browser }) => {
      const context = await browser.newContext(width === 768 ? TABLET : PHONE(width, width === 360 ? 780 : width === 430 ? 932 : 844));
      const page = await context.newPage();
      await page.goto(`/${locale}`);
      const banner = page.getByTestId("consent-banner");
      await expect(banner).toBeVisible();
      await page.waitForTimeout(400);
      expect(await coveredControls(page)).toEqual([]);
      // The same two buttons, side by side.
      const r = (await banner.getByTestId("consent-reject").boundingBox())!;
      const a = (await banner.getByTestId("consent-accept").boundingBox())!;
      expect(Math.abs(r.width - a.width)).toBeLessThan(1);
      expect(Math.abs(r.height - a.height)).toBeLessThan(1);
      expect(await banner.getByTestId("consent-reject").getAttribute("class"))
        .toBe(await banner.getByTestId("consent-accept").getAttribute("class"));
      // Scrolled to, it is still the same banner and still covers nothing.
      await banner.scrollIntoViewIfNeeded();
      expect(await coveredControls(page)).toEqual([]);
      await context.close();
    });
  }
}

// --- 5. the thread's header, the hint, the tablet's first screen ---------------

for (const [locale, width] of [["es", 360], ["en", 360], ["fr", 360], ["fr", 390]] as const) {
  test(`5.${locale}.${width} «${CATALOGS[locale].guestSpace.newConversation}» stays on the record button's row`, async ({ browser }) => {
    const { context, page } = await panel(browser, `row-${locale}-${width}`, locale, PHONE(width, 780));
    await mockTurns(page, [sse([["start", {}], ["token", { content: "Respuesta de prueba." }],
      ["final", { citations: [], evidence_citations: [] }]])]);
    await say(page, "regurgita");
    await expect(page.getByText("Respuesta de prueba.")).toBeVisible();
    const rec = (await page.getByTestId("record-consult").boundingBox())!;
    const fresh = (await page.getByTestId("new-conversation").boundingBox())!;
    expect(Math.abs(rec.y - fresh.y), "one row").toBeLessThan(1);
    expect(fresh.x + fresh.width).toBeLessThanOrEqual(width);
    // The hint in the field reads whole: it fits the width of the field.
    const hint = await page.getByTestId("agent-canvas").locator("textarea").evaluate((el) => {
      const ta = el as HTMLTextAreaElement;
      const cs = getComputedStyle(ta);
      const ctx = document.createElement("canvas").getContext("2d")!;
      ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const room = ta.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      return { text: ta.placeholder, need: ctx.measureText(ta.placeholder).width, room };
    });
    expect(hint.text).toBe(CATALOGS[locale].guestSpace.followUpPlaceholder);
    expect(hint.need, `«${hint.text}» is cut`).toBeLessThanOrEqual(hint.room);
    await context.close();
  });
}

for (const locale of LOCALES) {
  test(`5.${locale} the empty field's hint reads whole at 360`, async ({ browser }) => {
    const { context, page } = await panel(browser, `hint-${locale}`, locale, PHONE(360, 780));
    const hint = await page.getByTestId("agent-canvas").locator("textarea").evaluate((el) => {
      const ta = el as HTMLTextAreaElement;
      const cs = getComputedStyle(ta);
      const ctx = document.createElement("canvas").getContext("2d")!;
      ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const room = ta.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      return { text: ta.placeholder, need: ctx.measureText(ta.placeholder).width, room };
    });
    expect(hint.need, `«${hint.text}» is cut`).toBeLessThanOrEqual(hint.room);
    await context.close();
  });
}

test("5. tablet: the empty panel starts at the top, no blank band above the greeting", async ({ browser }) => {
  const { context, page } = await panel(browser, "tablet-top", "es", TABLET);
  const gap = await page.evaluate(() => {
    const h1 = document.querySelector(".ad-agent-canvas h1")!.getBoundingClientRect();
    const rec = document.querySelector('[data-testid="record-consult"]')!.getBoundingClientRect();
    return h1.top - rec.bottom;
  });
  expect(gap, "blank between «Grabar la consulta» and the greeting").toBeLessThanOrEqual(40);
  await context.close();
});
