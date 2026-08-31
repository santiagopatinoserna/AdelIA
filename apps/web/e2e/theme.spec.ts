import { expect, test } from "@playwright/test";

// The colour system has two halves. The `@media (prefers-color-scheme: dark)`
// half is what almost everyone sees; the `[data-theme]` half is what the
// switcher will use and what the anti-flash script in app/[locale]/layout.tsx
// stamps on <html> before the first paint. Nothing exercises that second half
// in normal browsing, so it is the half that rots. These tests drive both.

const DARK_CANVAS = "#071813";
const LIGHT_CANVAS = "#f4f1e9";

async function tokens(page: import("@playwright/test").Page) {
  return page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const v = (n: string) => cs.getPropertyValue(n).trim();
    return {
      attr: document.documentElement.dataset.theme,
      colorScheme: cs.colorScheme,
      canvas: v("--color-canvas"),
      surface: v("--color-surface"),
      surface3: v("--color-surface-3"),
      ink: v("--color-ink"),
      focus: v("--color-focus"),
      lineControl: v("--color-line-control"),
      body: getComputedStyle(document.body).backgroundColor,
    };
  });
}

test("the system preference drives the scheme, and the ink is never pure white", async ({
  browser,
}) => {
  for (const [scheme, canvas] of [
    ["light", LIGHT_CANVAS],
    ["dark", DARK_CANVAS],
  ] as const) {
    const ctx = await browser.newContext({ colorScheme: scheme });
    const page = await ctx.newPage();
    await page.goto("/es");
    const t = await tokens(page);
    expect(t.colorScheme, `${scheme}: color-scheme`).toBe(scheme);
    expect(t.canvas, `${scheme}: canvas`).toBe(canvas);
    // The body must paint the canvas itself: a transparent body would show the
    // browser's own white behind the page in dark.
    expect(t.body, `${scheme}: body background`).toBe(
      scheme === "dark" ? "rgb(7, 24, 19)" : "rgb(244, 241, 233)",
    );
    // Deliberate: strong ink is off-white with a green cast, never #ffffff on
    // near-black, which is what glares at 3 a.m. with a baby in your arms.
    if (scheme === "dark") {
      expect(t.ink, "dark ink").toBe("#edf3ee");
      // In dark, elevation goes UP in luminance: a dialog is lighter than a card.
      expect(t.surface3).toBe("#1f4036");
      expect(t.surface).toBe("#102821");
    }
    await ctx.close();
  }
});

test("an explicit choice overrides the system in both directions", async ({ browser }) => {
  for (const [systemScheme, stored, wantCanvas] of [
    ["light", "dark", DARK_CANVAS],
    ["dark", "light", LIGHT_CANVAS],
  ] as const) {
    const ctx = await browser.newContext({ colorScheme: systemScheme });
    const page = await ctx.newPage();
    await page.goto("/es");
    // Exactly what the switcher will write, read back by the inline script in
    // the locale layout on the next load.
    await page.evaluate((t) => localStorage.setItem("adelia-theme", t), stored);
    await page.reload();
    const t = await tokens(page);
    expect(t.attr, `system=${systemScheme} stored=${stored}: data-theme`).toBe(stored);
    expect(t.colorScheme, `system=${systemScheme} stored=${stored}: color-scheme`).toBe(stored);
    expect(t.canvas, `system=${systemScheme} stored=${stored}: canvas`).toBe(wantCanvas);
    await ctx.close();
  }
});

test("a blocked localStorage falls back to the system scheme", async ({ browser }) => {
  const ctx = await browser.newContext({ colorScheme: "dark" });
  await ctx.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new DOMException("blocked", "SecurityError");
      },
    });
  });
  const page = await ctx.newPage();
  await page.goto("/es");
  const t = await tokens(page);
  expect(t.attr, "no data-theme is stamped").toBeUndefined();
  expect(t.canvas, "the system scheme still applies").toBe(DARK_CANVAS);
  await ctx.close();
});
