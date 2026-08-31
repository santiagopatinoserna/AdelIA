import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";

// Serious/critical violations fail; minor/moderate get logged for later.
async function scan(page: import("@playwright/test").Page, label: string) {
  // Audit the SETTLED UI: wait for entrance animations (ad-rise fade/slide) to
  // finish so contrast is measured at final opacity, not mid-fade. Capped so a
  // looping animation can never hang the scan.
  await page.evaluate(() =>
    Promise.race([
      Promise.allSettled(document.getAnimations().map((a) => a.finished)),
      new Promise((resolve) => setTimeout(resolve, 1500)),
    ]),
  );
  const results = await new AxeBuilder({ page }).analyze();
  const blocking = results.violations.filter((v) =>
    ["serious", "critical"].includes(v.impact ?? ""),
  );
  for (const v of results.violations) {
    console.log(
      `[a11y:${label}] ${v.impact} ${v.id}: ${v.help} (${v.nodes.length} nodes)`,
    );
  }
  expect(blocking, `${label}: ${blocking.map((v) => v.id).join(", ")}`).toEqual([]);
}

test("a11y: public pages", async ({ page }) => {
  await page.goto("/es");
  await scan(page, "home");
  await page.goto("/es/signin");
  await scan(page, "signin");
  await page.goto("/es/profesionales");
  await scan(page, "profesionales");
});

test("a11y: authenticated surfaces", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(
    `e2e-a11y-${Date.now()}@adelia.test`,
  );
  const context = await browser.newContext();
  await context.addCookies([cookie]);
  const page = await context.newPage();

  for (const [path, label] of [
    ["/es/dashboard", "dashboard"],
    ["/es/dashboard/settings", "settings"],
    ["/es/dashboard/chat", "chat"],
    ["/es/dashboard/briefings", "briefings"],
    ["/es/dashboard/briefings/new", "briefings/new"],
    ["/es/dashboard/questionnaire", "questionnaire"],
    ["/es/dashboard/consulta", "consulta"],
    ["/es/dashboard/ingestion", "ingestion"],
    ["/es/dashboard/ingestion/apple-health", "ingestion/apple-health"],
    ["/es/dashboard/ingestion/ccd", "ingestion/ccd"],
    ["/es/dashboard/enrichment", "enrichment"],
    ["/es/dashboard/enrichment/labs", "enrichment/labs"],
    ["/es/dashboard/enrichment/drugs", "enrichment/drugs"],
    ["/es/dashboard/enrichment/profiles", "enrichment/profiles"],
    ["/es/dashboard/enrichment/trials", "enrichment/trials"],
    ["/es/dashboard/enrichment/genomics", "enrichment/genomics"],
    ["/es/dashboard/enrichment/codes", "enrichment/codes"],
    ["/es/dashboard/upload", "upload"],
    ["/es/dashboard/consulta/grabar", "consulta/grabar"],
  ] as const) {
    await page.goto(path);
    await scan(page, label);
  }
  await context.close();
});

// DARK SCHEME. The dark palette is a scheme of its own (globals.css, tokens
// under prefers-color-scheme: dark), not a filter, so every contrast pair has
// to be re-measured with the browser asking for dark. Reduced motion on
// purpose: commit a664166 learned that axe reads the .ad-rise fade as low
// contrast if it scans mid-animation.
test("a11y: dark scheme, public and authenticated", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(
    `e2e-a11y-dark-${Date.now()}@adelia.test`,
  );
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    colorScheme: "dark",
    reducedMotion: "reduce",
  });
  await context.addCookies([cookie]);
  const page = await context.newPage();

  // The scheme really is dark before anything is asserted about it: without
  // this, a regression that dropped the dark block would still pass every
  // contrast check, in light.
  await page.goto("/es");
  const canvas = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--color-canvas").trim(),
  );
  expect(canvas, "dark --color-canvas").toBe("#071813");
  await scan(page, "dark/home");

  for (const [path, label] of [
    ["/es/dashboard", "dark/dashboard"],
    ["/es/dashboard/overview", "dark/overview"],
    ["/es/dashboard/settings", "dark/settings"],
    ["/es/dashboard/chat", "dark/chat"],
    ["/es/dashboard/consulta/grabar", "dark/consulta/grabar"],
    ["/es/privacidad", "dark/privacidad"],
  ] as const) {
    await page.goto(path);
    await scan(page, label);
  }
  await context.close();
});

// Phone shell (390x844, mobile emulation): the header is icon-only ("Subir"
// needs its accessible name, 44px box), the language pill lives in Settings,
// and the tab bar is the navigation. Same rule as above: serious/critical fail.
test("a11y: phone shell", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(
    `e2e-a11y-phone-${Date.now()}@adelia.test`,
  );
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  await context.addCookies([cookie]);
  const page = await context.newPage();

  for (const [path, label] of [
    ["/es/dashboard", "phone/dashboard"],
    ["/es/dashboard/overview", "phone/overview"],
    ["/es/dashboard/settings", "phone/settings"],
    ["/es/dashboard/consulta/grabar", "phone/consulta/grabar"],
  ] as const) {
    await page.goto(path);
    await scan(page, label);
  }
  // 44px touch targets on the phone shell: the icon-only "Subir" (named),
  // the wordmark, the language pill in Settings, the data export link and
  // the "Cerrar" of the install guide.
  async function atLeast44(locator: import("@playwright/test").Locator, what: string) {
    await expect(locator, what).toBeVisible();
    const box = await locator.boundingBox();
    expect(box, what).not.toBeNull();
    expect(box!.width, `${what}: width`).toBeGreaterThanOrEqual(44);
    expect(box!.height, `${what}: height`).toBeGreaterThanOrEqual(44);
  }
  const banner = page.getByRole("banner");
  await atLeast44(banner.getByRole("link", { name: "Subir archivo" }), "Subir");
  await atLeast44(banner.getByRole("link", { name: /Adel\s*IA/ }), "wordmark");
  await page.goto("/es/dashboard/settings");
  for (const button of await page.getByRole("group", { name: "Idioma" }).getByRole("button").all()) {
    await atLeast44(button, "language button");
  }
  await atLeast44(page.getByRole("link", { name: "Descargar todos mis datos" }), "export link");
  // Headless Chromium offers no native install prompt, so Settings shows the
  // guide entry; guard it anyway in case a browser does fire beforeinstallprompt.
  const guideCta = page.getByRole("button", { name: "Ver cómo instalarla" });
  if (await guideCta.isVisible()) {
    await guideCta.click();
    await atLeast44(page.getByRole("dialog").getByRole("button", { name: "Cerrar" }), "guide close");
  }
  await context.close();
});

// The focus ring is a DOM fact, not a token fact: scripts/check-contrast.mjs
// proves the two tones clear 3:1 on every ground, and proved it happily while
// `focus:outline-none` (Tailwind utilities, a later cascade layer) cancelled
// the outline on every text field and every filled .ad-btn painted its own
// `box-shadow: var(--shadow-soft)` over the ring's companion tone. These two
// assertions are what the token guard structurally cannot see.
test("focus: the two-tone amber ring is really painted, on a field and on a filled button", async ({
  browser,
}) => {
  const { cookie } = await seedUserAndSessionCookie(
    `e2e-focus-ring-${Date.now()}@adelia.test`,
  );
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.addCookies([cookie]);
  const page = await context.newPage();

  const RING = "rgb(11, 26, 20) 0px 0px 0px 2px, rgba(163, 110, 31, 0.26) 0px 0px 0px 6px";

  // A text field: :focus-visible matches on programmatic focus for text input.
  await page.goto("/es/dashboard/chat");
  const field = page.getByRole("textbox").first();
  await field.focus();
  const fieldRing = await field.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { outlineStyle: cs.outlineStyle, outlineColor: cs.outlineColor, boxShadow: cs.boxShadow };
  });
  expect(fieldRing.outlineStyle, "the field's outline is painted").toBe("solid");
  expect(fieldRing.outlineColor, "the ring is the product's amber").toBe("rgb(163, 110, 31)");
  expect(fieldRing.boxShadow, "both tones of the ring").toBe(RING);

  // A filled button: :focus-visible needs the keyboard, so tab until one is
  // focused. Its own drop shadow must not eat the ring.
  await page.goto("/es/dashboard");
  await page.getByRole("heading", { level: 1 }).waitFor();
  let reached = false;
  for (let i = 0; i < 20 && !reached; i++) {
    await page.keyboard.press("Tab");
    reached = await page.evaluate(
      () => document.activeElement?.classList.contains("ad-btn-primary") ?? false,
    );
  }
  // .ad-btn transitions box-shadow over 0.18s and getComputedStyle returns the
  // INTERPOLATED value: read at t=0 it reports --shadow-soft even when the ring
  // is being applied. Let it settle.
  await page.waitForTimeout(500);
  const filled = !reached
    ? null
    : await page.evaluate(() => {
        const el = document.activeElement as HTMLElement;
        const cs = getComputedStyle(el);
        return {
          boxShadow: cs.boxShadow,
          outlineColor: cs.outlineColor,
          label: el.getAttribute("aria-label") ?? el.textContent?.trim() ?? "",
        };
      });
  expect(filled, "a filled .ad-btn-primary was reached by keyboard").not.toBeNull();
  expect(filled!.outlineColor, `"${filled!.label}" ring colour`).toBe("rgb(163, 110, 31)");
  expect(filled!.boxShadow, `"${filled!.label}" keeps both tones, not --shadow-soft`).toBe(RING);
  await context.close();
});
