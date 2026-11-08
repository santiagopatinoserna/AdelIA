import { expect, test, type Page, type Request } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { seedUserAndSessionCookie } from "./utils/session";

// Consented visitor journeys (decision of Santiago, 2026-11-07), against the
// real API with no LLM key. What is pinned:
//
//   * nothing leaves the page before an answer, after "Rechazar", or with the
//     browser's GPC signal: not one request to /api/analytics/collect;
//   * with "Aceptar", the batches carry pages, taps, steps of the funnel and
//     the origin of the visit, and never the question she typed (every body
//     is searched for it);
//   * the banner never covers the question box, the dictation button or the
//     record button at 390 px, steps aside while she types, and is not asked
//     inside her space (the panel), where Settings holds the choice;
//   * the journey reaches the admin page, which only an admin can open.
//
// The questions are red flags: the deterministic guard answers them before
// any model, so the guest panel answers for real without a key.

const SHOTS = join(homedir(), "dev/adelia-design/shots/analytics");
const PHONE = { width: 390, height: 844 };
const QUESTION = "Mi bebé ha convulsionado y no reacciona";
const FOLLOW_UP = "Ahora ha convulsionado otra vez, ¿qué hago?";
// The API drops bots, and headless Chrome says so in its user agent; the
// journey test is a visitor on a phone.
const PHONE_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 " +
  "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1";
// The API on :8110 runs with this address on ADMIN_EMAILS (see the report).
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "e2e-analytics-admin@adelia.test";

function watchAnalytics(page: Page) {
  const collect: string[] = [];
  const consent: Record<string, unknown>[] = [];
  const all: Request[] = [];
  page.on("request", (req) => {
    const url = req.url();
    if (!url.includes("/api/analytics/")) return;
    all.push(req);
    if (url.endsWith("/collect")) collect.push(req.postData() ?? "");
    if (url.endsWith("/consent")) consent.push(JSON.parse(req.postData() ?? "{}"));
  });
  return { collect, consent, all };
}

function events(bodies: string[]) {
  return bodies.flatMap((b) => (JSON.parse(b) as { events: Record<string, unknown>[] }).events);
}

/** Leave the page the way a phone does: the tab goes to the background. */
async function hide(page: Page) {
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

function overlaps(a: { x: number; y: number; width: number; height: number }, b: typeof a) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

test.describe.configure({ mode: "serial" });

test("before any answer nothing is measured, and the banner shows", async ({ page }) => {
  await page.setViewportSize(PHONE);
  const seen = watchAnalytics(page);
  await page.goto("/es");
  const banner = page.getByTestId("consent-banner");
  await expect(banner).toBeVisible();
  await expect(banner.getByRole("button", { name: "Aceptar" })).toBeVisible();
  await expect(banner.getByRole("button", { name: "Rechazar" })).toBeVisible();
  await page.mouse.wheel(0, 800);
  await page.getByTestId("home-about").locator("summary").click();
  await page.waitForTimeout(6000);
  await hide(page);
  await page.waitForTimeout(500);
  expect(seen.all).toHaveLength(0);
  const stored = await page.evaluate(() => Object.keys(localStorage).filter((k) => k.includes("analytics")));
  expect(stored).toEqual([]);
});

test("Rechazar and Aceptar are the same size, 44 px, and the text is two lines", async ({ page }) => {
  for (const locale of ["es", "en", "fr"]) {
    await page.setViewportSize(PHONE);
    await page.goto(`/${locale}`);
    const banner = page.getByTestId("consent-banner");
    const reject = await banner.getByTestId("consent-reject").boundingBox();
    const accept = await banner.getByTestId("consent-accept").boundingBox();
    expect(reject!.height).toBeGreaterThanOrEqual(44 - 0.05);
    expect(Math.abs(reject!.width - accept!.width)).toBeLessThan(1);
    expect(Math.abs(reject!.height - accept!.height)).toBeLessThan(1);
    const [rejectClass, acceptClass] = await Promise.all([
      banner.getByTestId("consent-reject").getAttribute("class"),
      banner.getByTestId("consent-accept").getAttribute("class"),
    ]);
    expect(rejectClass).toBe(acceptClass);
    const lines = await banner.locator("p").evaluate((p) => {
      const lh = parseFloat(getComputedStyle(p).lineHeight);
      return Math.round(p.getBoundingClientRect().height / lh);
    });
    expect(lines, locale).toBeLessThanOrEqual(2);
    const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollW).toBeLessThanOrEqual(PHONE.width);
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, `banner-landing-${locale}-390.png`) });
  }
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/es");
  await expect(page.getByTestId("consent-banner")).toBeVisible();
  await page.screenshot({ path: join(SHOTS, "banner-landing-es-390-dark.png") });
});

test("the banner never covers the question box, the mic or the record button at 390 px", async ({
  page,
}) => {
  mkdirSync(SHOTS, { recursive: true });
  test.setTimeout(120_000);
  await page.setViewportSize(PHONE);
  await page.goto("/es");
  const banner = page.getByTestId("consent-banner");
  await expect(banner).toBeVisible();
  const box = await banner.boundingBox();
  for (const target of [
    page.locator("#demo-question"),
    page.getByRole("button", { name: "Dictar la pregunta" }),
    page.getByRole("button", { name: "Preguntar", exact: true }),
    page.getByTestId("landing-record"),
  ]) {
    if (!(await target.count())) continue;
    const t = await target.boundingBox();
    expect(overlaps(box!, t!), await target.evaluate((e) => e.outerHTML.slice(0, 60))).toBe(false);
  }
  await page.screenshot({ path: join(SHOTS, "banner-landing-es-390.png") });

  // Typing: the banner steps aside for the keyboard, and comes back only a
  // moment after the field lets go, so it never lands under a tap.
  await page.locator("#demo-question").focus();
  await expect(banner).toBeHidden();
  await page.locator("#demo-question").blur();
  await page.waitForTimeout(150);
  await expect(banner).toBeHidden();
  await expect(banner).toBeVisible();

  // The "new version" toast rises above the banner instead of under it.
  await page.evaluate(() => {
    const toast = document.createElement("div");
    toast.className = "ad-update-toast fixed inset-x-3 bottom-[calc(4.25rem+env(safe-area-inset-bottom))] z-40";
    toast.id = "fake-toast";
    toast.textContent = "x";
    document.body.appendChild(toast);
  });
  const toast = await page.locator("#fake-toast").boundingBox();
  expect(overlaps(box!, toast!)).toBe(false);

  // Her space is not asked: no sheet over the chat box, the record button
  // or the first screen of the panel. Settings holds the same choice.
  await page.getByTestId("landing-record").click();
  await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar/, { timeout: 30_000 });
  await page.goto("/es/dashboard");
  await expect(page.getByTestId("record-consult")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("[data-testid=agent-canvas] textarea")).toBeInViewport();
  await expect(banner).toHaveCount(0);
  await page.goto("/es/dashboard/settings");
  await expect(page.getByTestId("settings-consent").getByRole("button", { name: "Aceptar" })).toBeVisible();
  await expect(banner).toHaveCount(0);
});

test("Rechazar: the answer is kept and nothing is ever sent", async ({ page }) => {
  await page.setViewportSize(PHONE);
  const seen = watchAnalytics(page);
  await page.goto("/es");
  await page.getByTestId("consent-reject").click();
  await expect(page.getByTestId("consent-banner")).toBeHidden();
  await page.mouse.wheel(0, 800);
  await page.getByTestId("home-about").locator("summary").click();
  await page.reload();
  await expect(page.getByTestId("consent-banner")).toBeHidden();
  await page.waitForTimeout(6000);
  await hide(page);
  await page.waitForTimeout(500);
  expect(seen.collect).toHaveLength(0);
  // The proof of the answer: a random id, the choice, the version. No visitor.
  expect(seen.consent).toHaveLength(1);
  expect(seen.consent[0]).toMatchObject({ choice: "rejected", source: "banner" });
  expect(Object.keys(seen.consent[0]).sort()).toEqual(["choice", "consent_id", "source", "version"]);
  const visitor = await page.evaluate(() => localStorage.getItem("adelia-analytics-visitor"));
  expect(visitor).toBeNull();
});

test("GPC: no banner, no request at all", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(Navigator.prototype, "globalPrivacyControl", { get: () => true });
  });
  await page.setViewportSize(PHONE);
  const seen = watchAnalytics(page);
  await page.goto("/es");
  await page.waitForTimeout(1000);
  await expect(page.getByTestId("consent-banner")).toHaveCount(0);
  await page.mouse.wheel(0, 800);
  await page.getByTestId("home-about").locator("summary").click();
  await page.goto("/es/privacidad#cookies");
  await expect(page.getByTestId("consent-control")).toContainText("GPC");
  await expect(page.getByTestId("consent-control").getByRole("button")).toHaveCount(0);
  await page.waitForTimeout(6000);
  await hide(page);
  await page.waitForTimeout(500);
  expect(seen.all).toHaveLength(0);
});

test.describe("with consent", () => {
  test.use({ userAgent: PHONE_UA });

  test("the whole journey is measured, never her words, and reaches the admin page", async ({
    page,
    context,
  }) => {
    test.setTimeout(180_000);
    mkdirSync(SHOTS, { recursive: true });
    await page.setViewportSize(PHONE);
    const seen = watchAnalytics(page);
    const campaign = `e2e-${Date.now().toString(36)}`;
    await page.goto(`/es?utm_source=tiktok&utm_medium=social&utm_campaign=${campaign}&utm_content=video-1`);
    await page.getByTestId("consent-accept").click();
    await expect(page.getByTestId("consent-banner")).toBeHidden();
    await page.mouse.wheel(0, 2000);

    await page.locator("#demo-question").fill(QUESTION);
    await page.getByRole("button", { name: "Preguntar", exact: true }).click();
    await expect(page).toHaveURL(/\/es\/dashboard\/?$/, { timeout: 30_000 });
    await expect(page.locator('[data-role="assistant"]').first()).toContainText("112", {
      timeout: 30_000,
    });
    const field = page.getByPlaceholder("Pregunta más sobre esto");
    await field.fill(FOLLOW_UP);
    await field.press("Enter");
    await expect(page.locator('[data-role="assistant"]')).toHaveCount(2, { timeout: 30_000 });
    await page.getByTestId("record-consult").click();
    await expect(page).toHaveURL(/consulta\/grabar/);
    await hide(page);
    await expect.poll(() => events(seen.collect).length, { timeout: 15_000 }).toBeGreaterThan(5);

    // The proof first, then batches with the expected shape.
    expect(seen.consent[0]).toMatchObject({ choice: "accepted", source: "banner" });
    const all = events(seen.collect);
    const steps = all.filter((e) => e.type === "step").map((e) => e.step);
    for (const step of [
      "landing_view", "first_interaction", "guest_created", "question_sent", "answer_shown",
      "follow_up",
    ]) {
      expect(steps, step).toContain(step);
    }
    expect(all.some((e) => e.type === "pageview" && e.path === "/es")).toBe(true);
    expect(all.some((e) => e.type === "pageview" && e.path === "/es/dashboard")).toBe(true);
    expect(all.some((e) => e.type === "click" && e.element === "landing-ask")).toBe(true);
    expect(all.some((e) => e.type === "click" && e.element === "record-consult")).toBe(true);
    expect(all.some((e) => e.type === "scroll")).toBe(true);
    const first = JSON.parse(seen.collect[0]);
    expect(first.context).toMatchObject({
      utm_source: "tiktok", utm_medium: "social", utm_campaign: campaign, utm_content: "video-1",
      locale: "es", landing_path: "/es",
    });
    expect(first.visitor_id).toMatch(/^[0-9a-f-]{36}$/);
    // Her words are nowhere: not the question, not the follow-up, not a piece.
    const everything = [...seen.collect, ...seen.consent.map((c) => JSON.stringify(c))].join("\n");
    for (const fragment of [QUESTION, FOLLOW_UP, "convulsionado", "reacciona", "bebé"]) {
      expect(everything).not.toContain(fragment);
      expect(everything).not.toContain(encodeURIComponent(fragment));
    }

    // The admin page: an admin sees this campaign's visit and its timeline.
    const { cookie } = await seedUserAndSessionCookie(ADMIN_EMAIL);
    await context.clearCookies();
    await context.addCookies([cookie]);
    // A short link of the social networks is counted without consent and
    // listed on the same page (2026-11-08).
    expect((await page.request.get("/r/g02", { maxRedirects: 0 })).status()).toBe(302);
    await page.goto("/es/dashboard/admin?days=7");
    await expect(page.getByTestId("admin-analytics")).toBeVisible();
    await expect(page.getByTestId("admin-links")).toContainText("/r/g02");
    await expect(page.getByTestId("admin-links")).toContainText("g02_fiebre3m");
    await expect(page.getByTestId("admin-funnel")).toContainText("Pregunta enviada");
    await expect(page.getByTestId("admin-sources")).toContainText(campaign);
    const recent = page.getByTestId("admin-recent").locator("details").filter({ hasText: campaign });
    await expect(recent.first()).toBeVisible();
    await recent.first().locator("summary").click();
    await expect(recent.first()).toContainText("Repregunta");
    const html = await page.content();
    expect(html).not.toContain("convulsionado");
    const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollW).toBeLessThanOrEqual(PHONE.width);
    await page.screenshot({ path: join(SHOTS, "admin-es-390.png"), fullPage: true });
    await page.goto("/es/dashboard/settings");
    await expect(page.getByTestId("settings-admin")).toBeVisible();

    // Withdrawing in Settings forgets this browser's journey.
    const before = seen.consent.length;
    await page.getByTestId("settings-consent").getByRole("button", { name: "Retirar mi permiso" }).click();
    await expect.poll(() => seen.consent.length).toBe(before + 1);
    expect(seen.consent[before]).toMatchObject({ choice: "withdrawn", source: "settings" });
    expect(seen.consent[before].forget_visitor).toBe(first.visitor_id);
    expect(await page.evaluate(() => localStorage.getItem("adelia-analytics-visitor"))).toBeNull();
  });
});

test("the admin page is a 404 for an account that is not an admin", async ({ browser }) => {
  const context = await browser.newContext({ viewport: PHONE });
  const { cookie } = await seedUserAndSessionCookie(`e2e-not-admin-${Date.now()}@adelia.test`);
  await context.addCookies([cookie]);
  const page = await context.newPage();
  const res = await page.goto("/es/dashboard/admin");
  expect(res?.status()).toBe(404);
  await expect(page.getByTestId("admin-analytics")).toHaveCount(0);
  await page.goto("/es/dashboard/settings");
  await expect(page.getByTestId("settings-consent")).toBeVisible();
  await expect(page.getByTestId("settings-admin")).toHaveCount(0);
  await context.close();
});
