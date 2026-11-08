import { type BrowserContext, type Page, expect, test } from "@playwright/test";

import en from "../messages/en.json";
import es from "../messages/es.json";
import fr from "../messages/fr.json";
import { armModelGuard, note, pageErrors, shot } from "./browser";
import { URGENT_QUESTIONS, boxesOverlap, isAnalyticsCollect, leakedFragments } from "./kit";

// Check 6: the analytics banner on the landing, at 390x844. It shows on a
// first visit in es/en/fr; "Aceptar" and "Rechazar" are the same button; it
// covers neither the question box, the dictation button, "Preguntar" nor the
// record button; after "Rechazar" not one batch leaves, and after "Aceptar"
// the batches carry no text of a question.
//
// Production keeps nothing of this run: the two analytics calls are answered
// 204 inside the browser (stubAnalytics), so no consent proof and no batch
// reaches the API, and what the page tried to send is still seen here. No
// question is ever sent: one is typed and never submitted, and the model
// guard is armed.

const RUN_DIR = process.env.PROD_SMOKE_RUN_DIR!;
const CATALOGS = { es, en, fr } as const;
// Typed, never sent. Every fragment is searched for in what leaves.
const TYPED = "Prueba de humo: mi bebé tiene mocos y tos";
const FRAGMENTS = [TYPED, "mocos", "tos y", "bebé tiene", ...URGENT_QUESTIONS];

type Seen = { collect: string[]; consent: Record<string, unknown>[] };

/** Answer the analytics calls in the browser and keep what they carried. */
async function stubAnalytics(context: BrowserContext): Promise<Seen> {
  const seen: Seen = { collect: [], consent: [] };
  await context.route(
    (url) => url.pathname.startsWith("/api/analytics/"),
    async (route) => {
      const req = route.request();
      if (isAnalyticsCollect(req.url())) seen.collect.push(req.postData() ?? "");
      else seen.consent.push(JSON.parse(req.postData() || "{}") as Record<string, unknown>);
      await route.fulfill({ status: 204 });
    },
  );
  return seen;
}

/** Leave the page the way a phone does: the tab goes to the background. */
async function hide(page: Page): Promise<void> {
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

/** Scroll, open the "about" block, type a question and let go of the field. */
async function browseWithoutSending(page: Page): Promise<void> {
  await page.mouse.wheel(0, 1200);
  await page.getByTestId("home-about").locator("summary").click();
  await page.mouse.wheel(0, -2400);
  await page.locator("#demo-question").fill(TYPED);
  await page.locator("#demo-question").blur();
  await page.waitForTimeout(1000);
}

for (const locale of ["es", "en", "fr"] as const) {
  const c = CATALOGS[locale].consent;

  test(`6.${locale} Banner de cookies (${locale})`, async ({ page, context }) => {
    const guard = await armModelGuard(context);
    const seen = await stubAnalytics(context);
    const errors = pageErrors(page);

    await page.goto(`/${locale}`);
    const banner = page.getByTestId("consent-banner");
    await expect(banner).toBeVisible();
    const reject = banner.getByTestId("consent-reject");
    const accept = banner.getByTestId("consent-accept");
    await expect(reject).toHaveText(c.reject);
    await expect(accept).toHaveText(c.accept);

    // The same button: same box, same classes, a thumb's height.
    const [r, a] = [(await reject.boundingBox())!, (await accept.boundingBox())!];
    expect(Math.abs(r.width - a.width), "width of Rechazar vs Aceptar").toBeLessThan(1);
    expect(Math.abs(r.height - a.height), "height of Rechazar vs Aceptar").toBeLessThan(1);
    expect(r.height, "button height").toBeGreaterThanOrEqual(44 - 0.05);
    expect(await reject.getAttribute("class")).toBe(await accept.getAttribute("class"));

    // It covers none of the ways in.
    const box = (await banner.boundingBox())!;
    const field = page.locator("#demo-question");
    const targets = {
      "question box": field,
      "dictation button": field.locator("xpath=..").locator("button"),
      Preguntar: page.locator('[data-track="landing-ask"]'),
      "record button": page.getByTestId("landing-record"),
    };
    const covered: string[] = [];
    for (const [name, target] of Object.entries(targets)) {
      if ((await target.count()) === 0) continue; // no dictation in this browser
      const t = await target.first().boundingBox();
      if (t && boxesOverlap(box, t)) covered.push(name);
    }
    expect(covered, "controls under the banner").toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await shot(page, RUN_DIR, `06-banner-${locale}`);

    // Before any answer nothing is measured.
    await page.waitForTimeout(1500);
    expect(seen.collect, "batches before an answer").toEqual([]);
    expect(seen.consent, "consent calls before an answer").toEqual([]);
    expect(errors, "uncaught page errors").toEqual([]);
    expect(guard.modelRequests, "requests to an answering endpoint").toEqual([]);
    note(`banner ${locale}: same buttons ${Math.round(r.width)}x${Math.round(r.height)}, covers nothing, nothing sent`);
  });
}

test("6.rechazar Rechazar: nada sale, y la respuesta se recuerda", async ({ page, context }) => {
  const guard = await armModelGuard(context);
  const seen = await stubAnalytics(context);

  await page.goto("/es");
  await page.getByTestId("consent-reject").click();
  await expect(page.getByTestId("consent-banner")).toBeHidden();
  await page.reload();
  await expect(page.getByTestId("consent-banner")).toBeHidden();

  await browseWithoutSending(page);
  await page.waitForTimeout(6000); // past the 5 s flush of lib/analytics.ts
  await hide(page);
  await page.waitForTimeout(1000);

  expect(seen.collect, "batches after Rechazar").toEqual([]);
  expect(seen.consent.map((x) => x.choice)).toEqual(["rejected"]);
  expect(await page.evaluate(() => localStorage.getItem("adelia-analytics-visitor"))).toBeNull();
  expect(guard.modelRequests, "requests to an answering endpoint").toEqual([]);
  note("Rechazar: banner gone after reload, 0 batches, 1 consent call (stubbed), no visitor id");
});

test("6.aceptar Aceptar: se mide la visita, nunca el texto de una pregunta", async ({ page, context }) => {
  const guard = await armModelGuard(context);
  const seen = await stubAnalytics(context);

  await page.goto("/es");
  await page.getByTestId("consent-accept").click();
  await expect(page.getByTestId("consent-banner")).toBeHidden();
  await browseWithoutSending(page);
  await hide(page);

  await expect.poll(() => seen.collect.length, { timeout: 15_000 }).toBeGreaterThan(0);
  const events = seen.collect.flatMap(
    (b) => (JSON.parse(b) as { events?: { type: string }[] }).events ?? [],
  );
  expect(events.some((e) => e.type === "pageview"), "a page view").toBe(true);
  const sent = [...seen.collect, ...seen.consent.map((x) => JSON.stringify(x))];
  expect(leakedFragments(sent, FRAGMENTS), "question text in what left").toEqual([]);
  expect(seen.consent.map((x) => x.choice)).toEqual(["accepted"]);
  expect(guard.modelRequests, "requests to an answering endpoint").toEqual([]);
  expect(guard.violations, "requests the model guard stopped").toEqual([]);
  const kinds = [...new Set(events.map((e) => e.type))].sort().join(", ");
  note(`Aceptar: ${seen.collect.length} batch(es), ${events.length} events (${kinds}), no question text; stubbed, nothing stored`);
});
