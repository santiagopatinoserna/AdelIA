import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser, type Page } from "@playwright/test";

import enMessages from "@/messages/en.json";
import esMessages from "@/messages/es.json";
import frMessages from "@/messages/fr.json";

// The landing on a phone, for a mother who has the baby in one arm. The page
// is short on purpose: what AdelIA is, one real answer, where answers come
// from, what it costs, and the legal footer. This file pins that:
//
//   * the first screen holds the headline and both buttons, whole;
//   * the whole page stays short (a ceiling on the scroll height);
//   * what the page must keep is there, and what was removed does not return;
//   * nothing scrolls sideways, touch targets are 44 px, and axe is clean.

const MESSAGES = { es: esMessages, en: enMessages, fr: frMessages } as const;
const LOCALES = ["es", "en", "fr"] as const;

const PHONE = { width: 390, height: 844 }; // iPhone 12-15
const SE = { width: 375, height: 667 }; // the tightest common phone

// Total scroll height at 390 px, in CSS px. Before the minimal redesign the
// page was 2,268 px with most of it folded away; the ceiling guards the
// opposite drift, a section quietly growing back.
const HEIGHT_CEILING = 2_600;

// Blink reports a 2.75rem (44 px) box as 43.999969482421875 under mobile
// emulation; same epsilon and reason as showcase.spec.ts.
const TAP_MIN = 44 - 0.05;

async function phone(browser: Browser, viewport = PHONE, scheme: "light" | "dark" = "light") {
  const context = await browser.newContext({
    viewport,
    isMobile: true,
    hasTouch: true,
    reducedMotion: "reduce",
    colorScheme: scheme,
  });
  const page = await context.newPage();
  return { context, page };
}

const scrollHeight = (page: Page) => page.evaluate(() => document.documentElement.scrollHeight);

test.describe("landing on a phone", () => {
  for (const viewport of [PHONE, SE]) {
    for (const locale of LOCALES) {
      test(`first screen ${viewport.width}x${viewport.height} ${locale}: headline and both buttons, whole`, async ({
        browser,
      }) => {
        const m = MESSAGES[locale].home;
        const { context, page } = await phone(browser, viewport);
        await page.goto(`/${locale}`);

        await expect(page.getByRole("heading", { level: 1 })).toHaveText(m.hero);

        const demo = page.getByRole("link", { name: m.demoLink, exact: true }).first();
        const start = page.getByRole("link", { name: m.cta, exact: true }).first();
        for (const [name, el] of [["demo", demo], ["start", start]] as const) {
          await expect(el, `${name} button`).toBeVisible();
          const box = (await el.boundingBox())!;
          expect(box.height, `${name}: touch height`).toBeGreaterThanOrEqual(TAP_MIN);
          expect(box.y + box.height, `${name} inside the first screen`).toBeLessThanOrEqual(
            viewport.height,
          );
        }

        const w = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
        }));
        expect(w.scroll, "scrolls sideways").toBe(w.client);
        await context.close();
      });
    }
  }

  for (const locale of LOCALES) {
    test(`${locale}: short page, with the proof, the sources, the price and the legal footer`, async ({
      browser,
    }) => {
      const m = MESSAGES[locale].home;
      const { context, page } = await phone(browser);
      await page.goto(`/${locale}`);

      const height = await scrollHeight(page);
      expect(
        height,
        `landing is ${height}px tall at 390px; ceiling ${HEIGHT_CEILING}`,
      ).toBeLessThanOrEqual(HEIGHT_CEILING);

      await expect(page.getByText(m.proofAnswer)).toBeVisible();
      await expect(page.getByRole("heading", { level: 2, name: m.evTitle })).toBeVisible();
      await expect(page.locator("section#pricing").getByText(m.prT2Trial)).toBeVisible();
      await expect(page.getByRole("contentinfo")).toContainText(m.footerDisclaimer);
      await expect(page.getByRole("link", { name: m.footerPrivacy })).toBeVisible();
      await expect(page.getByRole("link", { name: m.footerTerms })).toBeVisible();

      // Removed on purpose; if one comes back, argue for it here.
      for (const id of ["day", "features", "how", "story"]) {
        await expect(page.locator(`section#${id}`), `#${id} is gone`).toHaveCount(0);
      }
      await expect(page.getByTestId("landing-fold-toggle")).toHaveCount(0);
      await context.close();
    });
  }

  test("a11y: no serious or critical violation, light and dark", async ({ browser }) => {
    for (const scheme of ["light", "dark"] as const) {
      const { context, page } = await phone(browser, PHONE, scheme);
      await page.goto("/es");
      await page.waitForLoadState("networkidle").catch(() => {});
      const results = await new AxeBuilder({ page }).analyze();
      const bad = results.violations.filter((v) =>
        ["serious", "critical"].includes(v.impact ?? ""),
      );
      expect(bad.map((v) => `${v.id}: ${v.nodes.length}`), `axe, ${scheme}`).toEqual([]);
      await context.close();
    }
  });
});

test.describe("landing on a desktop", () => {
  test("is the same short page: sources and price are there", async ({ browser }) => {
    for (const locale of LOCALES) {
      const m = MESSAGES[locale].home;
      const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      const page = await context.newPage();
      await page.goto(`/${locale}`);
      for (const id of ["evidence", "pricing"]) {
        await expect(page.locator(`section#${id}`), `${locale}: #${id}`).toBeVisible();
      }
      await expect(page.getByRole("heading", { level: 2, name: m.evTitle })).toHaveCount(1);
      await context.close();
    }
  });
});
