import { randomUUID } from "node:crypto";

import { expect, test, type Browser, type Page } from "@playwright/test";
import { Pool } from "pg";

import { seedUserAndSessionCookie } from "./utils/session";

// Phone viewports: iPhone SE (375x667, the tightest common one) for the
// original checks, 390x844 (iPhone 12-15) for the overflow and keyboard
// checks of the PWA work. Patient-facing flows must work one-handed.
const SE = { width: 375, height: 667 };
const PHONE = { width: 390, height: 844 };

function pgPool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

const seededUserIds: string[] = [];

test.afterAll(async () => {
  if (seededUserIds.length === 0) return;
  const pool = pgPool();
  try {
    await pool.query(`DELETE FROM documents WHERE user_id = ANY($1::uuid[])`, [seededUserIds]);
    await pool.query(`DELETE FROM users WHERE id = ANY($1::uuid[])`, [seededUserIds]);
  } finally {
    await pool.end();
  }
});

// A ready document with the kind of file name a scanner or a hospital
// portal produces: one long token with no break opportunity. Before the
// grid fix its min-content widened /overview to 404px on a 390px phone.
async function insertDocument(userId: string, fileName: string, source: "web" | "consulta" = "web") {
  const pool = pgPool();
  try {
    await pool.query(
      `INSERT INTO documents (id, user_id, source, mime_type, s3_key, raw_text, processed_at)
       VALUES (gen_random_uuid(), $1, $2, 'application/pdf', $3, 'texto de prueba', now())`,
      [userId, source, `users/${userId}/${randomUUID()}-${fileName}`],
    );
  } finally {
    await pool.end();
  }
}

// isMobile: phone emulation, so scrollbars are overlays like on a real
// phone. Desktop Chromium reserves an 11px gutter (`scrollbar-gutter:
// stable` in globals.css) that made scrollWidth read 11px UNDER clientWidth.
async function openAs(browser: Browser, tag: string, viewport: { width: number; height: number }) {
  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-m-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
  );
  seededUserIds.push(userId);
  const context = await browser.newContext({ viewport, isMobile: true, hasTouch: true });
  await context.addCookies([cookie]);
  const page = await context.newPage();
  return { context, page, userId };
}

// scrollWidth === clientWidth on <html>: the strict form of "no sideways
// scroll" (the old `> clientWidth + 1` let a 1px spill through).
async function widths(page: Page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
}

test("mobile: dashboard fits and core nav is reachable", async ({ browser }) => {
  const { context, page } = await openAs(browser, "home", SE);

  await page.goto("/es/dashboard");
  // The agent home: greeting as the page's h1, tab bar below.
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  // No horizontal overflow — the page must not scroll sideways on a phone.
  const w = await widths(page);
  expect(w.scrollWidth, "page overflows horizontally on 375px").toBe(w.clientWidth);

  // The tab bar reaches the consult section from the phone.
  await page.getByRole("navigation", { name: "Inicio" }).getByRole("link", { name: "Consulta" }).click();
  await expect(page).toHaveURL(/\/dashboard\/consulta$/);
  await context.close();
});

test("mobile: chat sidebar is a drawer, not a fixed column", async ({ browser }) => {
  const { context, page } = await openAs(browser, "chat", SE);

  await page.goto("/es/dashboard/chat");

  // The conversation input must be visible — the sidebar must NOT eat the width.
  const input = page.getByPlaceholder(/Mi bebé no duerme bien/); // chat.placeholder (es)
  await expect(input).toBeVisible();
  const box = await input.boundingBox();
  expect(box, "chat input not rendered").not.toBeNull();
  // On a 375px screen the input spans most of the width: 375 minus the
  // padding and the "Enviar" button leaves ~247px (a fixed 256px sidebar
  // would squeeze it to ~100px).
  expect(box!.width).toBeGreaterThan(200);
  // ...and sit above the tab bar, not behind it.
  const bar = await page.getByRole("navigation", { name: "Inicio" }).boundingBox();
  expect(bar).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(bar!.y + 0.5);

  // The drawer toggle exists and opens the sessions panel.
  const toggle = page.getByRole("button", { name: "Ver conversaciones" });
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.getByRole("button", { name: /Nueva conversación/ })).toBeVisible();

  // No horizontal overflow.
  const w = await widths(page);
  expect(w.scrollWidth, "chat overflows horizontally on 375px").toBe(w.clientWidth);
  await context.close();
});

test("mobile: upload screen is usable", async ({ browser }) => {
  const { context, page } = await openAs(browser, "upload", SE);

  await page.goto("/es/dashboard/upload");
  await expect(page.getByRole("heading", { name: "Subir documento" })).toBeVisible();
  await expect(page.locator('input[type="file"]')).toBeAttached();
  await context.close();
});

test("mobile 390: /dashboard and /dashboard/overview never scroll sideways, with or without documents", async ({ browser }) => {
  // Returning user: quick-access grids + a document list with hostile names.
  const { context, page, userId } = await openAs(browser, "overview", PHONE);
  await insertDocument(userId, "informe_analitica_completa_hospital_universitario_12_08_2026_pediatria_final.pdf");
  await insertDocument(userId, "cartilla.pdf", "consulta");
  // Layout shifts after the first paint (CLS, user input excluded). The
  // check-in card used to be inserted after hydration and pushed the whole
  // overview down: 0.138 on a 390px phone. It is decided server-side now.
  await page.addInitScript(() => {
    const w = window as unknown as { __cls: number };
    w.__cls = 0;
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) {
        if (!e.hadRecentInput) w.__cls += e.value;
      }
    }).observe({ type: "layout-shift", buffered: true });
  });

  for (const path of ["/es/dashboard", "/es/dashboard/overview"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const w = await widths(page);
    expect(w.clientWidth).toBe(390);
    expect(w.scrollWidth, `${path} scrolls sideways`).toBe(w.clientWidth);
    await page.waitForTimeout(1500);
    const cls = await page.evaluate(() => (window as unknown as { __cls: number }).__cls);
    expect(cls, `${path} shifts layout after the first paint (CLS)`).toBe(0);
  }
  // The check-in card is in the server HTML (first paint), not inserted later.
  await expect(page.getByRole("button", { name: "Ahora no" })).toBeVisible();
  // The document list is on screen and the tab bar sits flush with the viewport.
  await expect(page.getByRole("heading", { name: "Mis documentos" })).toBeVisible();
  const bar = await page.getByRole("navigation", { name: "Inicio" }).boundingBox();
  expect(bar).not.toBeNull();
  expect(bar!.x).toBe(0);
  expect(bar!.width).toBe(390);
  expect(bar!.y + bar!.height).toBeLessThanOrEqual(844);
  await context.close();

  // First run (no documents): the 3-step welcome grid.
  const fresh = await openAs(browser, "firstrun", PHONE);
  await fresh.page.goto("/es/dashboard/overview");
  await expect(fresh.page.getByRole("heading", { name: "Bienvenida a AdelIA" })).toBeVisible();
  const w = await widths(fresh.page);
  expect(w.scrollWidth, "first-run overview scrolls sideways").toBe(w.clientWidth);
  await fresh.context.close();
});

test("mobile 390: the tab bar gets out of the way while the chat field has focus", async ({ browser }) => {
  const { context, page } = await openAs(browser, "keyboard", PHONE);
  await page.goto("/es/dashboard");

  const input = page.getByRole("textbox", { name: "Escribe o pulsa el micro…" });
  const bar = page.getByRole("navigation", { name: "Inicio" });
  await expect(input).toBeVisible();
  await expect(bar).toBeVisible();
  // Resting state: the input row ends above the bar (nothing hidden behind it).
  const inputBox = await input.boundingBox();
  const barBox = await bar.boundingBox();
  expect(inputBox!.y + inputBox!.height).toBeLessThanOrEqual(barBox!.y + 0.5);

  // Focus alone is not a keyboard (physical keyboards, tablets): the bar stays.
  await input.focus();
  await expect(bar).toBeVisible();
  await expect(page.locator("html")).not.toHaveClass(/kb-open/);

  // Focus + the viewport shrinking to the keyboard's top edge = keyboard up:
  // the bar hides and the shell drops its reserved space.
  await page.setViewportSize({ width: 390, height: 500 });
  await expect(bar).toBeHidden();
  await expect(page.locator("html")).toHaveClass(/kb-open/);
  await expect(input).toBeVisible();
  await expect(input).toBeFocused();

  // Android Back: the keyboard closes, the field keeps focus. The bar is back.
  await page.setViewportSize(PHONE);
  await expect(bar).toBeVisible();
  await expect(page.locator("html")).not.toHaveClass(/kb-open/);
  await expect(input).toBeFocused();

  // Keyboard again, then blur = keyboard down: the bar is back.
  await page.setViewportSize({ width: 390, height: 500 });
  await expect(bar).toBeHidden();
  await page.getByRole("heading", { level: 1 }).click();
  await page.setViewportSize(PHONE);
  await expect(bar).toBeVisible();
  await expect(page.locator("html")).not.toHaveClass(/kb-open/);
  await context.close();
});
