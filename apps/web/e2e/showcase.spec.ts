import {
  expect,
  test,
  type Browser,
  type BrowserContextOptions,
  type Locator,
  type Page,
} from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";

// Capability showcase on the agent home (regression, UI side only). The one
// network call a card can trigger (the "ask" links → the chat page → POST
// /chat) is intercepted here, so nothing in this spec depends on an LLM or
// on any external service.

const TITLE = "Lo que AdelIA puede hacer por ti"; // showcase.title (es)
const ASK_QUESTION = "¿Es normal que con 13 meses solo quiera leche materna?"; // showcase.cards.ask.example (es)
const ALT_QUESTION = "¿Cuánto tarda un bebé en adaptarse a la guardería?"; // showcase.cards.ask.altQuestion (es)
const HIDE = "Ocultar por ahora"; // showcase.hide
const SHOW = "Mostrar"; // showcase.show
const COLLAPSED = "Ejemplos de lo que AdelIA puede hacer"; // showcase.collapsed
const STORAGE_KEY = "adelia:showcase:hidden"; // lib/showcase-storage SHOWCASE_HIDDEN_KEY
const ACTIONS = [
  "Grabar",
  "Preguntar",
  "Enlazar Telegram",
  "Subir",
  "Crear briefing",
  "Empezar",
  "Importar",
  "Ver ajustes",
];

const showcase = (page: Page) => page.getByTestId("capability-showcase");
const cards = (page: Page) => page.getByTestId("showcase-card");

async function linkTarget(link: Locator) {
  const url = new URL((await link.getAttribute("href")) ?? "", "http://e2e.local");
  return { pathname: url.pathname, q: url.searchParams.get("q") };
}

async function openHome(browser: Browser, tag: string, options: BrowserContextOptions = {}) {
  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-showcase-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
  );
  const context = await browser.newContext(options);
  await context.addCookies([cookie]);
  const page = await context.newPage();
  await page.goto("/es/dashboard");
  return { context, page, cookie, userId };
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

// Every card's controls must stay inside the card: no clipped labels, no
// action spilling onto the neighbour.
async function cardOverflow(page: Page) {
  return page.evaluate(() => {
    const out: string[] = [];
    for (const card of document.querySelectorAll<HTMLElement>('[data-testid="showcase-card"]')) {
      const cb = card.getBoundingClientRect();
      if (card.scrollWidth > card.clientWidth + 1) out.push(`card scrolls: ${card.textContent?.slice(0, 30)}`);
      for (const el of card.querySelectorAll<HTMLElement>("h3, p, a, button")) {
        const b = el.getBoundingClientRect();
        if (b.right > cb.right + 0.5 || b.left < cb.left - 0.5) {
          out.push(`${el.tagName} "${el.textContent?.trim().slice(0, 30)}" ${b.left.toFixed(0)}..${b.right.toFixed(0)} outside ${cb.left.toFixed(0)}..${cb.right.toFixed(0)}`);
        }
        if (el.scrollWidth > el.clientWidth + 1 && el.tagName !== "A" && el.tagName !== "BUTTON") {
          out.push(`${el.tagName} clipped: ${el.textContent?.trim().slice(0, 30)}`);
        }
      }
    }
    return out;
  });
}

test("showcase: title and the 8 capability cards, each with a visible action", async ({ browser }) => {
  const { context, page } = await openHome(browser, "grid", { viewport: { width: 1280, height: 800 } });

  await expect(page.getByRole("heading", { level: 2, name: TITLE })).toBeVisible();
  await expect(cards(page)).toHaveCount(8);
  // The greeting stays the page's h1; the showcase is a section below it.
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);

  for (const name of ACTIONS) {
    await expect(showcase(page).getByRole("link", { name, exact: true }), `action "${name}"`).toBeVisible();
  }
  // lg+: four columns, nothing spilling out of its card.
  const tracks = await page.evaluate(
    () => getComputedStyle(document.querySelector('[data-testid="showcase-grid"]')!).gridTemplateColumns.split(" ").length,
  );
  expect(tracks).toBe(4);
  expect(await cardOverflow(page)).toEqual([]);
  await context.close();
});

test("showcase: 'Grabar' navigates to the consultation recorder", async ({ browser }) => {
  const { context, page } = await openHome(browser, "record", { viewport: { width: 1280, height: 800 } });

  await showcase(page).getByRole("link", { name: "Grabar", exact: true }).click();
  await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar$/);
  await context.close();
});

test("showcase: 'Preguntar' opens the chat, sends the example question once and shows the evidence citation", async ({ browser }) => {
  const { context, page } = await openHome(browser, "ask", { viewport: { width: 1280, height: 800 } });
  const captured = { bodies: [] as { question?: string; locale?: string }[] };
  await mockChat(page, captured);

  // Both "ask" controls are real links into the chat page with the question
  // in the URL (compared decoded: Next encodes query spaces as "+").
  const primary = showcase(page).getByRole("link", { name: "Preguntar", exact: true });
  expect(await linkTarget(primary)).toEqual({ pathname: "/es/dashboard/chat", q: ASK_QUESTION });
  const alt = showcase(page).getByRole("link", { name: new RegExp(ALT_QUESTION.replace(/[?¿]/g, "\\$&")) });
  expect(await linkTarget(alt)).toEqual({ pathname: "/es/dashboard/chat", q: ALT_QUESTION });

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

  // The secondary question goes the same way.
  await page.goto("/es/dashboard");
  await showcase(page).getByRole("link", { name: new RegExp(ALT_QUESTION.replace(/[?¿]/g, "\\$&")) }).click();
  await expect.poll(() => captured.bodies.length).toBe(2);
  expect(captured.bodies[1]?.question).toBe(ALT_QUESTION);
  await context.close();
});

test("showcase: 'Ocultar por ahora' keeps focus, lasts the session for this user, not for another", async ({ browser }) => {
  const { context, page, cookie, userId } = await openHome(browser, "hide", { viewport: { width: 1280, height: 800 } });
  await expect(cards(page)).toHaveCount(8);

  const hideBtn = page.getByRole("button", { name: HIDE, exact: true });
  await expect(hideBtn).toHaveAttribute("aria-expanded", "true");
  await hideBtn.click();
  await expect(showcase(page)).toContainText(COLLAPSED);
  const showBtn = showcase(page).getByRole("button", { name: SHOW, exact: true });
  await expect(showBtn).toBeVisible();
  // Disclosure pattern: the same control stays focused and flips aria-expanded.
  await expect(showBtn).toBeFocused();
  await expect(showBtn).toHaveAttribute("aria-expanded", "false");
  await expect(cards(page)).toHaveCount(0);
  expect(await page.evaluate((k) => window.sessionStorage.getItem(k), STORAGE_KEY)).toBe(userId);

  // Same tab, reload: still collapsed.
  await page.reload();
  await expect(showcase(page).getByRole("button", { name: SHOW, exact: true })).toBeVisible();
  await expect(cards(page)).toHaveCount(0);

  // "Mostrar" brings it back in the same session, focus still on the toggle.
  await showcase(page).getByRole("button", { name: SHOW, exact: true }).click();
  await expect(cards(page)).toHaveCount(8);
  await expect(page.getByRole("button", { name: HIDE, exact: true })).toBeFocused();
  expect(await page.evaluate((k) => window.sessionStorage.getItem(k), STORAGE_KEY)).toBeNull();

  // Hide again, then another user signs in on this very tab (same
  // sessionStorage): the flag is theirs, not this account's.
  await page.getByRole("button", { name: HIDE, exact: true }).click();
  await expect(cards(page)).toHaveCount(0);
  const other = await seedUserAndSessionCookie(`e2e-showcase-other-${Date.now()}@adelia.test`);
  await context.clearCookies();
  await context.addCookies([other.cookie]);
  await page.reload();
  await expect(page.getByRole("heading", { level: 2, name: TITLE })).toBeVisible();
  await expect(cards(page)).toHaveCount(8);

  // Visiting the sign-in page (every re-login goes through it) clears the flag.
  await context.clearCookies();
  await context.addCookies([cookie]);
  await page.goto("/es/dashboard");
  await expect(cards(page)).toHaveCount(0);
  await page.goto("/es/signin");
  await expect.poll(() => page.evaluate((k) => window.sessionStorage.getItem(k), STORAGE_KEY)).toBeNull();
  await page.goto("/es/dashboard");
  await expect(cards(page)).toHaveCount(8);

  // A brand-new browser context (= new session, fresh sessionStorage, same
  // user) shows the showcase again.
  await page.getByRole("button", { name: HIDE, exact: true }).click();
  await expect(cards(page)).toHaveCount(0);
  const fresh = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await fresh.addCookies([cookie]);
  const page2 = await fresh.newPage();
  await page2.goto("/es/dashboard");
  await expect(page2.getByRole("heading", { level: 2, name: TITLE })).toBeVisible();
  await expect(cards(page2)).toHaveCount(8);

  await fresh.close();
  await context.close();
});

test("showcase: tablet (768x1024, card rail visible) gets 2 columns and nothing spills out of a card", async ({ browser }) => {
  const { context, page } = await openHome(browser, "tablet", { viewport: { width: 768, height: 1024 } });
  await expect(cards(page)).toHaveCount(8);

  const metrics = await page.evaluate(() => {
    const grid = document.querySelector('[data-testid="showcase-grid"]') as HTMLElement;
    const card = document.querySelector('[data-testid="showcase-card"]') as HTMLElement;
    return {
      tracks: getComputedStyle(grid).gridTemplateColumns.split(" ").length,
      cardWidth: card.getBoundingClientRect().width,
      bodyScrollWidth: document.documentElement.scrollWidth,
      bodyClientWidth: document.documentElement.clientWidth,
    };
  });
  expect(metrics.tracks).toBe(2);
  expect(metrics.cardWidth).toBeGreaterThan(150);
  expect(metrics.bodyScrollWidth).toBeLessThanOrEqual(metrics.bodyClientWidth);
  expect(await cardOverflow(page)).toEqual([]);
  await context.close();
});

test("showcase: phone (390x844) gets a carousel with all 8 cards, no horizontal body scroll, and keyboard focus fully on screen", async ({ browser }) => {
  const { context, page } = await openHome(browser, "mobile", { viewport: { width: 390, height: 844 } });

  await expect(page.getByRole("heading", { level: 2, name: TITLE })).toBeVisible();
  await expect(cards(page)).toHaveCount(8);

  const metrics = await page.evaluate(() => {
    const doc = document.documentElement;
    const grid = document.querySelector('[data-testid="showcase-grid"]') as HTMLElement;
    return {
      bodyScrollWidth: doc.scrollWidth,
      bodyClientWidth: doc.clientWidth,
      gridScrollWidth: grid.scrollWidth,
      gridClientWidth: grid.clientWidth,
      overflowX: getComputedStyle(grid).overflowX,
    };
  });
  expect(metrics.bodyScrollWidth, "body must not scroll horizontally").toBeLessThanOrEqual(metrics.bodyClientWidth);
  // The list itself is the scroller (cards wider than the viewport row).
  expect(metrics.overflowX).toBe("auto");
  expect(metrics.gridScrollWidth).toBeGreaterThan(metrics.gridClientWidth);

  // First card fits inside the viewport width (78vw, capped).
  const box = await cards(page).first().boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeLessThanOrEqual(390);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);

  // Tabbing through the carousel: each focused control is fully visible
  // (the card scrolls to its snap point instead of the focus ring landing
  // half off the right edge).
  await page.getByRole("button", { name: HIDE, exact: true }).focus();
  const seen: string[] = [];
  for (let i = 0; i < 3; i++) {
    await page.keyboard.press("Tab");
    const f = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      const b = el.getBoundingClientRect();
      return { text: el.textContent?.trim() ?? "", left: b.left, right: b.right, vw: document.documentElement.clientWidth };
    });
    seen.push(f.text);
    expect(f.left, `"${f.text}" left edge`).toBeGreaterThanOrEqual(0);
    expect(f.right, `"${f.text}" right edge`).toBeLessThanOrEqual(f.vw);
  }
  expect(seen[0]).toContain("Grabar");
  expect(seen[1]).toContain("Preguntar");
  await context.close();
});
