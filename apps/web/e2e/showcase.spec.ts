import {
  expect,
  test,
  type Browser,
  type BrowserContextOptions,
  type Page,
} from "@playwright/test";

import es from "../messages/es.json";
import { seedUserAndSessionCookie } from "./utils/session";
import { isoMonthsAgo, seedProfile } from "./utils/seed";

// The empty panel home (regression, UI side only). It used to be the
// capability showcase: three first-day rows, four chips and a "hide for now".
// On 2026-11-09 a mother said "hay demasiadas cosas, no sé dónde leer" and the
// showcase became one example question plus one folded "Más" with each door
// once (components/agent/panel-more.tsx). Every intention this spec held for
// the showcase holds for what replaced it:
//   * one display-serif headline, the greeting;
//   * every door present once, "Ajustes" a tab of the bottom bar, not repeated;
//   * "Grabar" reaches the recorder;
//   * the example question fits the child's age and is sent once, never again
//     on a reload;
//   * the disclosure keeps focus on the same control;
//   * nothing clipped at 360 to 1440 px in es, en and fr, touch targets 44 px,
//     the product's amber focus ring;
//   * the baby's real age, once, and nothing without a birth date.
// The answer is a route mock of POST /agent/turn: no LLM.

const MORE = es.panel.more;
const DOORS = [es.panel.briefing, es.panel.questionnaire, es.panel.import];
const SETTINGS_TAB = "Ajustes"; // dashboard.navSettings
const ASK_NO_AGE = es.showcaseAsk.noAge;
const ASK_YOUNG = es.showcaseAsk.young;
const ASK_TODDLER = es.showcaseAsk.toddler;

// Under mobile emulation Blink reports a 44 px box as 43.99997: see the
// history of this file. 0,05 px still catches a real 40 px control.
const TAP_MIN = 44 - 0.05;

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
  await expect(page.getByTestId("agent-canvas")).toBeVisible();
  return { context, page, cookie, userId };
}

const more = (page: Page) => page.getByTestId("panel-more");
async function openMore(page: Page) {
  await more(page).locator(":scope > summary").click();
  await expect(more(page)).toHaveAttribute("open", "");
}

// Nothing in the empty panel may be clipped horizontally: a cut has to land on
// the edge of a row, never inside a word.
async function textClipping(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  return page.evaluate(() => {
    const out: string[] = [];
    const column = document.querySelector<HTMLElement>(".ad-agent-canvas main")!;
    const cb = column.getBoundingClientRect();
    for (const el of column.querySelectorAll<HTMLElement>("h1, p, a, button, summary, label, span")) {
      if (!el.checkVisibility()) continue;
      const b = el.getBoundingClientRect();
      if (b.width === 0 && b.height === 0) continue;
      if (b.right > cb.right + 0.5 || b.left < cb.left - 0.5) {
        out.push(`${el.tagName} "${el.textContent?.trim().slice(0, 24)}" outside the column`);
      }
      if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== "visible") {
        out.push(`clipped: ${el.textContent?.trim().slice(0, 30)}`);
      }
    }
    return out;
  });
}

const sse = (events: [string, unknown][]) =>
  events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");

test("home: the greeting is the one serif headline, and every door is under Más once", async ({
  browser,
}) => {
  const { context, page } = await openHome(browser, "grid", { viewport: { width: 1280, height: 900 } });
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await openMore(page);
  // The base layer paints every h1..h4 in Fraunces: nothing in the panel but
  // the greeting may come out in the display face.
  const serif = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>(".ad-agent-canvas main *")]
      .filter((el) => el.checkVisibility() && el.tagName !== "H1" && !el.closest("h1") &&
        getComputedStyle(el).fontFamily.includes("Fraunces"))
      .map((el) => `${el.tagName} "${el.textContent?.trim().slice(0, 30)}"`),
  );
  expect(serif, "the greeting is the ONE display-serif headline").toEqual([]);
  expect(
    await page.evaluate(() => getComputedStyle(document.querySelector("h1")!).fontFamily),
  ).toContain("Fraunces");

  for (const name of DOORS) {
    await expect(page.getByRole("link", { name, exact: true }), name).toHaveCount(1);
  }
  // "Ajustes" is a door of the shell, not repeated in the panel.
  await expect(more(page).getByRole("link", { name: SETTINGS_TAB, exact: true })).toHaveCount(0);
  // No rail beside the column any more: the same suggestions were drawn twice.
  await expect(page.getByRole("complementary")).toHaveCount(0);
  expect(await textClipping(page)).toEqual([]);
  await context.close();
});

test("home: 'Grabar la consulta' navigates to the consultation recorder", async ({ browser }) => {
  const { context, page } = await openHome(browser, "record", { viewport: { width: 1280, height: 900 } });
  await page.getByTestId("record-consult").click();
  await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar$/);
  await context.close();
});

test("home: the example question is asked here, once, and a reload does not send it again", async ({
  browser,
}) => {
  const { context, page } = await openHome(browser, "ask", { viewport: { width: 1280, height: 900 } });
  const bodies: { message?: string; locale?: string }[] = [];
  await page.route("**/api/backend/agent/turn", async (route) => {
    bodies.push(route.request().postDataJSON() as { message?: string; locale?: string });
    await route.fulfill({
      status: 200, contentType: "text/event-stream",
      body: sse([["start", {}], ["token", { content: "Respuesta de prueba [ev_1]." }],
        ["final", { citations: [], evidence_citations: [{
          tag: "ev_1", source_id: "s1", chunk_id: "c1", title: "Guía de prueba", organization: "AEP",
          year: 2024, url: "https://example.org/guia", snippet: "Fragmento de prueba." }] }]]),
    });
  });
  // A fresh account has no child yet: the example names no age.
  const example = page.getByTestId("ask-example");
  await expect(example).toContainText(ASK_NO_AGE);
  await example.click();
  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0]?.message).toBe(ASK_NO_AGE);
  expect(bodies[0]?.locale).toBe("es");
  await expect(page.locator('[data-role="user"]')).toHaveText(ASK_NO_AGE);
  await expect(page.getByText("Respuesta de prueba")).toBeVisible();
  // Its source is one line away, not gone.
  await page.getByTestId("agent-sources").locator(":scope > summary").click();
  await expect(page.getByText("Guía de prueba", { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("ask-example")).toBeVisible();
  await page.waitForTimeout(500);
  expect(bodies.length).toBe(1);
  await context.close();
});

test("home: 'Más' is one disclosure, and the same control keeps focus", async ({ browser }) => {
  const { context, page } = await openHome(browser, "more", { viewport: { width: 1280, height: 900 } });
  const summary = more(page).locator(":scope > summary");
  await expect(summary).toHaveText(MORE);
  await expect(more(page)).not.toHaveAttribute("open", "");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(more(page)).toHaveAttribute("open", "");
  await expect(summary).toBeFocused();
  for (const name of DOORS) await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(more(page)).not.toHaveAttribute("open", "");
  await expect(summary).toBeFocused();
  // Folded again on the next visit: it never takes the first screen by itself.
  await openMore(page);
  await page.reload();
  await expect(more(page)).not.toHaveAttribute("open", "");
  await context.close();
});

test("home: tablet (768x1024) is one column, nothing clipped, no sideways scroll", async ({ browser }) => {
  const { context, page } = await openHome(browser, "tablet", { viewport: { width: 768, height: 1024 } });
  await openMore(page);
  const m = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
    column: document.querySelector(".ad-agent-canvas main")!.getBoundingClientRect().width,
  }));
  expect(m.scroll).toBeLessThanOrEqual(m.client);
  expect(m.column).toBeGreaterThan(600);
  expect(await textClipping(page)).toEqual([]);
  await context.close();
});

test("home: phone (390x844) shows the conversation first, whole, touch targets over 44 px", async ({
  browser,
}) => {
  const { context, page } = await openHome(browser, "mobile", {
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  // The fold is the bottom of the scrolling column.
  const fold = await page.evaluate(() =>
    document.querySelector(".ad-agent-canvas main > div")!.getBoundingClientRect().bottom);
  for (const id of ["record-consult", "ask-example", "panel-more"]) {
    const box = (await page.getByTestId(id).boundingBox())!;
    expect(box.y + box.height, `${id} above the fold`).toBeLessThanOrEqual(fold);
  }
  await openMore(page);
  for (const el of [
    page.getByTestId("record-consult"), page.getByTestId("ask-example"),
    more(page).locator(":scope > summary"), ...await more(page).locator("a[href], button").all(),
  ]) {
    const box = (await el.boundingBox())!;
    expect(box.height, `${await el.innerText()} touch height`).toBeGreaterThanOrEqual(TAP_MIN);
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(390);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await textClipping(page)).toEqual([]);
  // "Ajustes" is one tab of the bottom bar.
  await expect(page.getByRole("link", { name: SETTINGS_TAB, exact: true })).toBeVisible();

  // Keyboard: the example and "Más" carry the product's amber ring, whole on screen.
  await page.getByTestId("record-consult").focus();
  for (const id of ["ask-example", "panel-more"]) {
    await page.keyboard.press("Tab");
    const f = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      const b = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return { id: (el.closest("[data-testid]") as HTMLElement)?.dataset.testid,
        color: cs.outlineColor, width: cs.outlineWidth, left: b.left, right: b.right,
        vw: document.documentElement.clientWidth };
    });
    expect(f.id).toBe(id);
    expect(f.color, `${id} focus ring colour`).toBe("rgb(163, 110, 31)");
    expect(f.width, `${id} focus ring width`).toBe("2px");
    expect(f.left - 6).toBeGreaterThanOrEqual(0);
    expect(f.right + 6).toBeLessThanOrEqual(f.vw);
  }
  await context.close();
});

// French carries the long words, 360 px is the common Android width, 1440 a
// laptop: a cut has to land on the edge of a row, never inside a word.
for (const [locale, width] of [
  ["fr", 390], ["fr", 360], ["en", 390], ["es", 360], ["es", 1280], ["fr", 1440],
] as const) {
  test(`home: nothing clipped in ${locale} at ${width}px, "Más" open`, async ({ browser }) => {
    const { context, page } = await openHome(
      browser, `clip-${locale}-${width}`,
      width < 600 ? { viewport: { width, height: 844 }, isMobile: true, hasTouch: true }
        : { viewport: { width, height: 900 } },
      locale,
    );
    await openMore(page);
    expect(await textClipping(page)).toEqual([]);
    await context.close();
  });
}

test("home: the baby's real age, once, under the greeting, and nothing without a birth date", async ({
  browser,
}) => {
  const bare = await openHome(browser, "mark-none", { viewport: { width: 390, height: 844 } });
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

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("¿Cómo está Martina?");
  const mark = page.getByTestId("growth-mark");
  await expect(mark).toHaveCount(1);
  // The name is already in the greeting: the line says the age and no more.
  await expect(mark).toHaveText("7 meses");
  const geo = await page.evaluate(() => {
    const h1 = document.querySelector("h1")!;
    const m = document.querySelector('[data-testid="growth-mark"]')!;
    return {
      afterGreeting: Boolean(h1.compareDocumentPosition(m) & Node.DOCUMENT_POSITION_FOLLOWING),
      height: m.getBoundingClientRect().height,
      colour: getComputedStyle(m).color === getComputedStyle(document.querySelector("h1")!).color,
    };
  });
  expect(geo.afterGreeting).toBe(true);
  expect(geo.height, "one line of height").toBeLessThan(40);
  expect(geo.colour, "quieter than the greeting").toBe(false);
  await context.close();
});

// The example fits the child on screen (seen in production on 2026-11-06:
// Lucía, 5 months, was offered a question about a 13-month-old). Neither the
// example nor the age line names an age that is not hers. ("Hoy" may name the
// age a vaccine was due at, "a los 2 meses": that is a date, not her age.)
for (const child of [
  { name: "Lucía", months: 5, question: ASK_YOUNG },
  { name: "Mateo", months: 20, question: ASK_TODDLER },
]) {
  test(`home: the example question fits ${child.name} at ${child.months} months`, async ({ browser }) => {
    const { cookie, userId } = await seedUserAndSessionCookie(
      `e2e-showcase-age-${child.months}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
    );
    await seedProfile(userId, { displayName: child.name, dateOfBirth: isoMonthsAgo(child.months) });
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await context.addCookies([cookie]);
    const page = await context.newPage();
    await page.goto("/es/dashboard");

    await expect(page.getByTestId("growth-mark")).toHaveText(`${child.months} meses`);
    await expect(page.getByTestId("ask-example")).toContainText(child.question);
    const text = [
      await page.getByTestId("growth-mark").innerText(),
      await page.getByTestId("ask-example").innerText(),
    ].join(" ");
    const ages = [...text.matchAll(/(\d+)\s*(?:meses|mes|semanas|años)\b/gu)].map((m) => Number(m[1]));
    expect(ages.filter((n) => n !== child.months), text).toEqual([]);
    await context.close();
  });
}
