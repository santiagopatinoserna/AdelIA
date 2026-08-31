import {
  expect,
  test,
  type Browser,
  type BrowserContextOptions,
  type Locator,
  type Page,
} from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";
import { isoMonthsAgo, seedDocument, seedProfile } from "./utils/seed";

// Capability showcase on the agent home (regression, UI side only). The one
// network call a card can trigger (the "ask" rows → the chat page → POST
// /chat) is intercepted here, so nothing in this spec depends on an LLM or
// on any external service.
//
// The screen has three visual weights, not eight identical cards:
//   * three PRIMARY rows (first day: ask, diary, record),
//   * four SECONDARY chips (second week: upload, briefing, questionnaire,
//     import),
//   * "Ajustes", the eighth capability, which is a tab of the bottom bar and
//     is deliberately NOT repeated here. Every test that counts the doors
//     checks the tab too, so the coverage is still eight.

const EYEBROW = "Primeros pasos"; // showcase.primaryEyebrow (es)
const ALSO = "Y también"; // showcase.secondaryEyebrow (es)
const ASK_QUESTION = "¿Es normal que con 13 meses solo quiera leche materna?"; // showcase.cards.ask.example (es)
const MOVED_QUESTION = "¿Cuánto tarda un bebé en adaptarse a la guardería?"; // chat.example4 (es), moved out of the ask card
const HIDE = "Ocultar por ahora"; // showcase.hide
const SHOW = "Mostrar"; // showcase.show
const COLLAPSED = "Ejemplos de lo que AdelIA puede hacer"; // showcase.collapsed
const SETTINGS_TAB = "Ajustes"; // dashboard.navSettings — the eighth door
const STORAGE_KEY = "adelia:showcase:hidden"; // lib/showcase-storage SHOWCASE_HIDDEN_KEY

// The three first-day rows, in the order a new parent needs them (spec 7.3).
const ROWS = [
  { key: "ask", action: "Preguntar" },
  { key: "diary", action: "Enlazar Telegram" },
  { key: "record", action: "Grabar" },
] as const;
// The four second-week chips.
const CHIPS = ["Subir informe", "Briefing", "Cuestionario", "Importar"] as const;

// Touch-height floors. The epsilon is not slack in the requirement: under
// mobile emulation Blink reports a 2.75rem (44 px) box as 43.999969482421875,
// a float artifact of the layout-unit conversion, so an exact `>= 44` fails on
// a chip that is 44 px by construction. 0,05 px is far below anything a finger
// or a screenshot can tell apart, and still catches a real 40 px control.
const EPS = 0.05;
const TAP_MIN = 44 - EPS; // --tap-md, the floor for any control
const ROW_MIN = 72 - EPS; // .ad-cap-row min-height

const showcase = (page: Page) => page.getByTestId("capability-showcase");
const rows = (page: Page) => page.getByTestId("showcase-card");
const chips = (page: Page) => page.getByTestId("showcase-chip");

async function linkTarget(link: Locator) {
  const url = new URL((await link.getAttribute("href")) ?? "", "http://e2e.local");
  return { pathname: url.pathname, q: url.searchParams.get("q") };
}

async function openHome(
  browser: Browser,
  tag: string,
  options: BrowserContextOptions = {},
  locale: "es" | "en" | "fr" = "es",
) {
  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-showcase-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
  );
  const context = await browser.newContext(options);
  await context.addCookies([cookie]);
  const page = await context.newPage();
  await page.goto(`/${locale}/dashboard`);
  return { context, page, cookie, userId };
}

// Every two-line clamp inside a card has to hold its whole sentence: one card
// of three ending in an ellipsis reads as a rendering accident, and the quote
// is the payload of the card. Only meaningful in the card layout (1264+); the
// row list below it does not render the detail at all.
async function clampedParagraphs(page: Page) {
  // Measure only once the webfonts are in: Hanken Grotesk is wider than the
  // fallback, so a measurement taken mid-swap reports a clamp that the reader
  // never sees (this test flaked exactly once, under parallel load).
  await page.evaluate(() => document.fonts.ready);
  return page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('[data-testid="showcase-card"] p.ad-clamp-2')]
      .filter((el) => el.getClientRects().length > 0 && el.scrollHeight > el.clientHeight + 1)
      .map((el) => `clamped: ${el.textContent?.trim().slice(0, 40)}`),
  );
}

// Deterministic chat turn (no LLM in e2e): captures what the chat page sends
// and answers with one evidence citation, so the citation rendering is
// exercised end to end.
const EVIDENCE_TITLE = "Guía de prueba sobre la adaptación a la guardería";
async function mockChat(page: Page, captured: { bodies: { question?: string; locale?: string }[] }) {
  await page.route("**/api/backend/chat", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    captured.bodies.push(route.request().postDataJSON() as { question?: string; locale?: string });
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body:
        'event: start\ndata: {"session_id":"00000000-0000-0000-0000-000000000001"}\n\n' +
        'event: token\ndata: {"content":"Respuesta de prueba."}\n\n' +
        "event: final\ndata: " +
        JSON.stringify({
          session_id: "00000000-0000-0000-0000-000000000001",
          citations: [],
          evidence_citations: [
            {
              tag: "ev_1",
              source_id: "s1",
              chunk_id: "c1",
              title: EVIDENCE_TITLE,
              organization: "AEP",
              year: 2024,
              url: "https://example.org/guia",
              snippet: "Fragmento de prueba.",
            },
          ],
        }) +
        "\n\n",
    });
  });
}

// Nothing inside a row or a chip may be clipped horizontally, and no title may
// be ellipsised: a cut has to land on the edge of a row, never inside a word.
async function textClipping(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  return page.evaluate(() => {
    const out: string[] = [];
    const items = document.querySelectorAll<HTMLElement>(
      '[data-testid="showcase-card"], [data-testid="showcase-chip"]',
    );
    for (const item of items) {
      const ib = item.getBoundingClientRect();
      if (item.scrollWidth > item.clientWidth + 1) out.push(`item scrolls: ${item.dataset.key}`);
      for (const el of item.querySelectorAll<HTMLElement>("h3, p, a, span")) {
        const b = el.getBoundingClientRect();
        if (b.width === 0 && b.height === 0) continue; // sr-only / hidden at this width
        if (b.right > ib.right + 0.5 || b.left < ib.left - 0.5) {
          out.push(
            `${el.tagName} "${el.textContent?.trim().slice(0, 24)}" ${b.left.toFixed(0)}..${b.right.toFixed(0)} outside ${ib.left.toFixed(0)}..${ib.right.toFixed(0)}`,
          );
        }
        // A truncated (ellipsised) title is a word cut in half.
        if (el.tagName === "H3" && el.scrollWidth > el.clientWidth + 1) {
          out.push(`title ellipsised: ${el.textContent?.trim().slice(0, 30)}`);
        }
      }
    }
    return out;
  });
}

test("showcase: three first-day rows, four second-week chips, the eighth door in the tab bar", async ({
  browser,
}) => {
  const { context, page } = await openHome(browser, "grid", { viewport: { width: 1280, height: 900 } });

  // One headline on the screen: the greeting. The section title stays an h2 in
  // the DOM (landmarks and aria-labelledby unchanged) but is painted as an
  // eyebrow — mono, not the display serif — so it cannot compete.
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  const title = page.getByRole("heading", { level: 2, name: EYEBROW });
  await expect(title).toBeVisible();
  const fonts = await page.evaluate(() => {
    const f = (sel: string) =>
      getComputedStyle(document.querySelector<HTMLElement>(sel)!).fontFamily;
    return { h1: f("h1"), h2: f("#capability-showcase-title") };
  });
  expect(fonts.h1, "the greeting is the display serif").toContain("Fraunces");
  expect(fonts.h2, "the section title is not a second serif headline").not.toContain("Fraunces");
  // ...and nothing else in the section may be serif either. The base layer
  // paints EVERY h1..h4 in Fraunces, so the three row titles (<h3>) come out
  // in the display face unless they explicitly say font-sans — four competing
  // serif headlines on the first screen, which is the defect this redesign
  // exists to close. Comparing only the h1 and the h2 cannot see that.
  const serifInShowcase = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('[data-testid="capability-showcase"] *')]
      .filter(
        (el) =>
          el.getClientRects().length > 0 &&
          getComputedStyle(el).fontFamily.includes("Fraunces"),
      )
      .map((el) => `${el.tagName} "${el.textContent?.trim().slice(0, 30)}"`),
  );
  expect(serifInShowcase, "the greeting is the ONE display-serif headline").toEqual([]);

  // Three rows, in order, each with its action; four chips.
  await expect(rows(page)).toHaveCount(3);
  expect(await rows(page).evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.key))).toEqual(
    ROWS.map((r) => r.key),
  );
  for (const { action } of ROWS) {
    await expect(showcase(page).getByRole("link", { name: action, exact: true }), `row "${action}"`).toBeVisible();
  }
  await expect(showcase(page)).toContainText(ALSO);
  await expect(chips(page)).toHaveCount(4);
  for (const label of CHIPS) {
    await expect(showcase(page).getByRole("link", { name: label, exact: true }), `chip "${label}"`).toBeVisible();
  }
  // The eighth capability is not repeated here: it is a tab of the bottom bar.
  await expect(showcase(page).getByRole("link", { name: SETTINGS_TAB, exact: true })).toHaveCount(0);

  // lg+: three columns of cards, four columns of chips, nothing clipped.
  const tracks = await page.evaluate(() => {
    const cols = (sel: string) =>
      getComputedStyle(document.querySelector(sel)!).gridTemplateColumns.split(" ").length;
    return { rows: cols('[data-testid="showcase-grid"]'), chips: cols('[data-testid="showcase-chips"]') };
  });
  expect(tracks).toEqual({ rows: 3, chips: 4 });
  expect(await textClipping(page)).toEqual([]);
  await context.close();
});

test("showcase: the cards are equal because their CONTENT is, not because one was stretched", async ({
  browser,
}) => {
  const { context, page } = await openHome(browser, "heights", { viewport: { width: 1280, height: 900 } });
  await expect(rows(page)).toHaveCount(3);

  const cards = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('[data-testid="showcase-card"]')].map((c) => {
      const cb = c.getBoundingClientRect();
      const action = c.querySelector<HTMLElement>("a")!.getBoundingClientRect();
      const pad = parseFloat(getComputedStyle(c).paddingBottom);
      return { key: c.dataset.key, height: cb.height, tail: cb.bottom - action.bottom - pad };
    }),
  );
  const heights = cards.map((c) => c.height);
  expect(Math.max(...heights) - Math.min(...heights), "cards differ in height").toBeLessThanOrEqual(1);
  // The old bug: the grid stretched every card to the tallest and `mt-auto`
  // pushed the action to the bottom, leaving ~150 px of nothing in card 1.
  for (const c of cards) {
    expect(c.tail, `dead space under the action of "${c.key}"`).toBeLessThan(8);
  }
  await context.close();
});

test("showcase: 'Grabar' navigates to the consultation recorder", async ({ browser }) => {
  const { context, page } = await openHome(browser, "record", { viewport: { width: 1280, height: 900 } });

  await showcase(page).getByRole("link", { name: "Grabar", exact: true }).click();
  await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar$/);
  await context.close();
});

test("showcase: 'Preguntar' opens the chat, sends the example question once and shows the evidence citation", async ({
  browser,
}) => {
  const { context, page, userId } = await openHome(browser, "ask", { viewport: { width: 1280, height: 900 } });
  const captured = { bodies: [] as { question?: string; locale?: string }[] };
  await mockChat(page, captured);
  // One document on the account, so the chat's empty state is the suggestion
  // list and not "upload something first".
  await seedDocument(userId);

  // "Preguntar" is a real link into the chat page with the question in the URL
  // (compared decoded: Next encodes query spaces as "+").
  const primary = showcase(page).getByRole("link", { name: "Preguntar", exact: true });
  expect(await linkTarget(primary)).toEqual({ pathname: "/es/dashboard/chat", q: ASK_QUESTION });

  await primary.click();
  await expect(page).toHaveURL(/\/es\/dashboard\/chat/);
  // The question is sent as the user's message (the chat path: documents + evidence, with citations).
  await expect.poll(() => captured.bodies.length).toBe(1);
  expect(captured.bodies[0]?.question).toBe(ASK_QUESTION);
  expect(captured.bodies[0]?.locale).toBe("es");
  await expect(page.getByText(ASK_QUESTION, { exact: true })).toBeVisible();
  await expect(page.getByText("Respuesta de prueba.")).toBeVisible();
  await expect(page.getByText(EVIDENCE_TITLE)).toBeVisible();
  // The one-shot question leaves the URL, so a reload does not send it again.
  await expect(page).toHaveURL(/\/es\/dashboard\/chat$/);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForTimeout(500);
  expect(captured.bodies.length).toBe(1);

  // The secondary question left the ask card (where it overflowed on a phone)
  // and is now one of the chat's own suggestions. It still reaches the thread.
  await expect(page.getByTestId("capability-showcase")).toHaveCount(0);
  const suggestion = page.getByRole("button", { name: MOVED_QUESTION });
  await expect(suggestion).toBeVisible();
  await suggestion.click();
  await expect.poll(() => captured.bodies.length).toBe(2);
  expect(captured.bodies[1]?.question).toBe(MOVED_QUESTION);
  await context.close();
});

test("showcase: 'Ocultar por ahora' keeps focus, lasts the session for this user, not for another", async ({
  browser,
}) => {
  const { context, page, cookie, userId } = await openHome(browser, "hide", { viewport: { width: 1280, height: 900 } });
  await expect(rows(page)).toHaveCount(3);
  await expect(chips(page)).toHaveCount(4);

  const hideBtn = page.getByRole("button", { name: HIDE, exact: true });
  await expect(hideBtn).toHaveAttribute("aria-expanded", "true");
  // The toggle is a real touch target, not a 20 px strip of underlined text.
  const hideBox = await hideBtn.boundingBox();
  expect(hideBox!.height, "toggle touch height").toBeGreaterThanOrEqual(TAP_MIN);
  await hideBtn.click();
  await expect(showcase(page)).toContainText(COLLAPSED);
  const showBtn = showcase(page).getByRole("button", { name: SHOW, exact: true });
  await expect(showBtn).toBeVisible();
  // Disclosure pattern: the same control stays focused and flips aria-expanded.
  await expect(showBtn).toBeFocused();
  await expect(showBtn).toHaveAttribute("aria-expanded", "false");
  await expect(rows(page)).toHaveCount(0);
  await expect(chips(page)).toHaveCount(0);
  expect(await page.evaluate((k) => window.sessionStorage.getItem(k), STORAGE_KEY)).toBe(userId);

  // Same tab, reload: still collapsed.
  await page.reload();
  await expect(showcase(page).getByRole("button", { name: SHOW, exact: true })).toBeVisible();
  await expect(rows(page)).toHaveCount(0);

  // "Mostrar" brings it back in the same session, focus still on the toggle.
  await showcase(page).getByRole("button", { name: SHOW, exact: true }).click();
  await expect(rows(page)).toHaveCount(3);
  await expect(chips(page)).toHaveCount(4);
  await expect(page.getByRole("button", { name: HIDE, exact: true })).toBeFocused();
  expect(await page.evaluate((k) => window.sessionStorage.getItem(k), STORAGE_KEY)).toBeNull();

  // Hide again, then another user signs in on this very tab (same
  // sessionStorage): the flag is theirs, not this account's.
  await page.getByRole("button", { name: HIDE, exact: true }).click();
  await expect(rows(page)).toHaveCount(0);
  const other = await seedUserAndSessionCookie(`e2e-showcase-other-${Date.now()}@adelia.test`);
  await context.clearCookies();
  await context.addCookies([other.cookie]);
  await page.reload();
  await expect(page.getByRole("heading", { level: 2, name: EYEBROW })).toBeVisible();
  await expect(rows(page)).toHaveCount(3);

  // Visiting the sign-in page (every re-login goes through it) clears the flag.
  await context.clearCookies();
  await context.addCookies([cookie]);
  await page.goto("/es/dashboard");
  await expect(rows(page)).toHaveCount(0);
  await page.goto("/es/signin");
  await expect.poll(() => page.evaluate((k) => window.sessionStorage.getItem(k), STORAGE_KEY)).toBeNull();
  await page.goto("/es/dashboard");
  await expect(rows(page)).toHaveCount(3);

  // A brand-new browser context (= new session, fresh sessionStorage, same
  // user) shows the showcase again.
  await page.getByRole("button", { name: HIDE, exact: true }).click();
  await expect(rows(page)).toHaveCount(0);
  const fresh = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await fresh.addCookies([cookie]);
  const page2 = await fresh.newPage();
  await page2.goto("/es/dashboard");
  await expect(page2.getByRole("heading", { level: 2, name: EYEBROW })).toBeVisible();
  await expect(rows(page2)).toHaveCount(3);
  await expect(chips(page2)).toHaveCount(4);

  await fresh.close();
  await context.close();
});

test("showcase: tablet (768x1024, card rail visible) keeps the full-width list, two columns of chips", async ({
  browser,
}) => {
  const { context, page } = await openHome(browser, "tablet", { viewport: { width: 768, height: 1024 } });
  await expect(rows(page)).toHaveCount(3);

  // At md the 320 px card rail already sits beside the chat column: three
  // cards there would be 133 px wide, so the rows stay rows.
  const metrics = await page.evaluate(() => {
    const cols = (sel: string) =>
      getComputedStyle(document.querySelector(sel)!).gridTemplateColumns.split(" ").length;
    const row = document.querySelector<HTMLElement>('[data-testid="showcase-card"]')!;
    return {
      rowTracks: cols('[data-testid="showcase-grid"]'),
      chipTracks: cols('[data-testid="showcase-chips"]'),
      rowWidth: row.getBoundingClientRect().width,
      bodyScrollWidth: document.documentElement.scrollWidth,
      bodyClientWidth: document.documentElement.clientWidth,
    };
  });
  expect(metrics.rowTracks).toBe(1);
  expect(metrics.chipTracks).toBe(2);
  expect(metrics.rowWidth).toBeGreaterThan(300);
  expect(metrics.bodyScrollWidth).toBeLessThanOrEqual(metrics.bodyClientWidth);
  expect(await textClipping(page)).toEqual([]);
  await context.close();
});

test("showcase: phone (390x844) shows all seven doors whole, no carousel, no clipped word, touch targets over 44 px", async ({
  browser,
}) => {
  const { context, page } = await openHome(browser, "mobile", {
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });

  await expect(page.getByRole("heading", { level: 2, name: EYEBROW })).toBeVisible();
  await expect(rows(page)).toHaveCount(3);
  await expect(chips(page)).toHaveCount(4);

  const metrics = await page.evaluate(() => {
    const doc = document.documentElement;
    const grid = document.querySelector('[data-testid="showcase-grid"]') as HTMLElement;
    const box = (el: Element) => {
      const b = el.getBoundingClientRect();
      return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, height: b.height };
    };
    return {
      bodyScrollWidth: doc.scrollWidth,
      bodyClientWidth: doc.clientWidth,
      // The list is no longer a horizontal scroller: there is nothing to cut.
      gridScrollWidth: grid.scrollWidth,
      gridClientWidth: grid.clientWidth,
      gridOverflowX: getComputedStyle(grid).overflowX,
      rows: [...document.querySelectorAll('[data-testid="showcase-card"]')].map(box),
      chips: [...document.querySelectorAll('[data-testid="showcase-chip"]')].map(box),
      // The chat column scrolls, not the page: this is the real fold.
      fold: document
        .querySelector('.ad-agent-canvas main > div')!
        .getBoundingClientRect().bottom,
      // Real rendering, not the computed `display` of the paragraph: the
      // detail is hidden by a WRAPPER (`hidden lg:block`, because .ad-clamp-2
      // would otherwise beat `hidden` on the <p> itself), and an element whose
      // ANCESTOR is display:none still reports its own display. Only
      // getClientRects() tells the truth about what is on screen.
      detailOnPhone: [...document.querySelectorAll('[data-testid="showcase-card"] p')].filter(
        (p) => p.getClientRects().length > 0,
      ).length,
      vw: doc.clientWidth,
      vh: window.innerHeight,
    };
  });
  expect(metrics.bodyScrollWidth, "body must not scroll horizontally").toBeLessThanOrEqual(
    metrics.bodyClientWidth,
  );
  expect(metrics.gridOverflowX, "no horizontal carousel any more").toBe("visible");
  expect(metrics.gridScrollWidth).toBeLessThanOrEqual(metrics.gridClientWidth + 1);

  // Every row and every chip is complete inside the viewport width, and the
  // first two rows (at least) sit whole above the fold. Nothing is cut, and
  // what a shorter screen would cut is the edge of a row, never a word.
  for (const [i, r] of metrics.rows.entries()) {
    expect(r.left, `row ${i} left`).toBeGreaterThanOrEqual(0);
    expect(r.right, `row ${i} right`).toBeLessThanOrEqual(metrics.vw);
    expect(r.height, `row ${i} touch height`).toBeGreaterThanOrEqual(ROW_MIN);
  }
  // The phone row carries the title and the concrete example, not the detail
  // paragraph: three rows plus four chips have to fit the first screen whole.
  expect(metrics.detailOnPhone, "one visible paragraph per row on a phone").toBe(3);
  expect(metrics.rows[1].bottom, "two whole rows above the fold").toBeLessThanOrEqual(metrics.fold);
  for (const [i, c] of metrics.chips.entries()) {
    expect(c.left, `chip ${i} left`).toBeGreaterThanOrEqual(0);
    expect(c.right, `chip ${i} right`).toBeLessThanOrEqual(metrics.vw);
    expect(c.height, `chip ${i} touch height`).toBeGreaterThanOrEqual(TAP_MIN);
  }
  // All seven doors sit above the fold: nothing is cut, cleanly or otherwise.
  expect(metrics.chips[3].bottom, "the last chip is still on the first screen").toBeLessThanOrEqual(
    metrics.fold,
  );
  expect(await textClipping(page)).toEqual([]);

  // The eighth capability is one tab of the bottom bar, not a ninth card.
  await expect(page.getByRole("link", { name: SETTINGS_TAB, exact: true })).toBeVisible();

  // Tabbing through the list: each focused control is fully on screen, ring
  // included (the amber focus ring extends 6 px beyond the element).
  await page.getByRole("button", { name: HIDE, exact: true }).focus();
  const seen: string[] = [];
  for (let i = 0; i < 3; i++) {
    await page.keyboard.press("Tab");
    const f = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      const b = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return {
        text: el.textContent?.trim() ?? "",
        outlineColor: cs.outlineColor,
        outlineWidth: cs.outlineWidth,
        left: b.left,
        right: b.right,
        top: b.top,
        bottom: b.bottom,
        vw: document.documentElement.clientWidth,
        vh: window.innerHeight,
      };
    });
    seen.push(f.text);
    // The focus ring is the product's own amber (--color-focus #a36e1f in the
    // light scheme), not a browser blue: that is the signal the accent is a
    // system and not one decorative icon.
    expect(f.outlineColor, `"${f.text}" focus ring colour`).toBe("rgb(163, 110, 31)");
    expect(f.outlineWidth, `"${f.text}" focus ring width`).toBe("2px");
    expect(f.left - 6, `"${f.text}" left edge with its focus ring`).toBeGreaterThanOrEqual(0);
    expect(f.right + 6, `"${f.text}" right edge with its focus ring`).toBeLessThanOrEqual(f.vw);
    expect(f.top, `"${f.text}" top edge`).toBeGreaterThanOrEqual(0);
    expect(f.bottom, `"${f.text}" bottom edge`).toBeLessThanOrEqual(f.vh);
  }
  // First-day order: ask, then diary, then record.
  expect(seen[0]).toContain("Preguntar");
  expect(seen[1]).toContain("Enlazar Telegram");
  expect(seen[2]).toContain("Grabar");
  await context.close();
});

// French is the other launch market and carries the long titles; 360 px is the
// common Android width. Without this the suite stays green whatever fr does,
// because every other test navigates to /es/dashboard only. A cut has to land
// on the edge of a row, never inside "20 h".
for (const [locale, width] of [
  ["fr", 390],
  ["fr", 360],
  ["en", 390],
  ["es", 360],
] as const) {
  test(`showcase: no title is ellipsised on a ${locale} phone at ${width}px`, async ({ browser }) => {
    const { context, page } = await openHome(
      browser,
      `clip-${locale}-${width}`,
      { viewport: { width, height: 844 }, isMobile: true, hasTouch: true },
      locale,
    );
    await expect(rows(page)).toHaveCount(3);
    expect(await textClipping(page)).toEqual([]);
    await context.close();
  });
}

// The card layout starts at 1264 (globals.css) precisely because 1024 could not
// hold this content: at 215 px the two-line clamp cut 5 of 6 paragraphs. These
// widths are the ones a laptop actually runs.
for (const [locale, width] of [
  ["es", 1280],
  ["fr", 1280],
  ["en", 1280],
  ["fr", 1440],
] as const) {
  test(`showcase: no clamped paragraph in the ${locale} cards at ${width}px`, async ({ browser }) => {
    const { context, page } = await openHome(
      browser,
      `clamp-${locale}-${width}`,
      { viewport: { width, height: 900 } },
      locale,
    );
    await expect(rows(page)).toHaveCount(3);
    const tracks = await page.evaluate(
      () =>
        getComputedStyle(document.querySelector('[data-testid="showcase-grid"]')!)
          .gridTemplateColumns.split(" ").length,
    );
    expect(tracks, "the card layout is on at this width").toBe(3);
    expect(await clampedParagraphs(page)).toEqual([]);
    expect(await textClipping(page)).toEqual([]);
    await context.close();
  });
}

test("home: the height mark carries the baby's real name and age, once, and nothing when there is no birth date", async ({
  browser,
}) => {
  // No profile yet: a height mark with no age means nothing, so there is none.
  const bare = await openHome(browser, "mark-none", { viewport: { width: 390, height: 844 } });
  await expect(bare.page.getByTestId("capability-showcase")).toBeVisible();
  await expect(bare.page.getByTestId("growth-mark")).toHaveCount(0);
  await bare.context.close();

  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-showcase-mark-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
  );
  await seedProfile(userId, { displayName: "Martina", dateOfBirth: isoMonthsAgo(7) });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await context.addCookies([cookie]);
  const page = await context.newPage();
  await page.goto("/es/dashboard");

  const mark = page.getByTestId("growth-mark");
  await expect(mark).toHaveCount(1); // one warm signal on the screen, exactly one
  await expect(mark).toHaveText("Martina · 7 meses");
  // It is a mark, not an ornament and not a rule: it sits between the greeting
  // and the list and costs one line of height. (It used to draw a flex-1
  // hairline, which at 1280 became a 781 px divider between the greeting and
  // the content the greeting introduces, echoing the header rule above it.)
  const order = await page.evaluate(() => {
    const h1 = document.querySelector("h1")!;
    const m = document.querySelector('[data-testid="growth-mark"]')!;
    const list = document.querySelector('[data-testid="showcase-grid"]')!;
    return {
      afterGreeting: h1.compareDocumentPosition(m) & Node.DOCUMENT_POSITION_FOLLOWING,
      beforeList: m.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING,
      height: m.getBoundingClientRect().height,
    };
  });
  expect(order.afterGreeting).toBeTruthy();
  expect(order.beforeList).toBeTruthy();
  expect(order.height, "one line of height, not an ornament").toBeLessThan(40);
  // No full-width rule: the mark hugs its label instead of stretching across
  // the column.
  const markWidth = await page.evaluate(() => {
    const m = document.querySelector('[data-testid="growth-mark"]')!;
    return {
      mark: m.getBoundingClientRect().width,
      column: (m.parentElement as HTMLElement).getBoundingClientRect().width,
    };
  });
  expect(markWidth.mark, "the mark is not a full-width divider").toBeLessThan(
    markWidth.column * 0.9,
  );
  await context.close();
});
