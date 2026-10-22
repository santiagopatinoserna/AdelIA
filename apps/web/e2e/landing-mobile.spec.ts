import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser, type Page } from "@playwright/test";

import enMessages from "@/messages/en.json";
import esMessages from "@/messages/es.json";
import frMessages from "@/messages/fr.json";

// The landing on a phone, for a mother who has the baby in one arm. The page
// is the demo: the question comes first, then where answers come from, what it
// costs, and the legal footer. This file pins that:
//
//   * the first screen holds the headline, the question field with its send
//     button, and the "Empezar" link (it was: headline and two buttons; the
//     "see the demo" button is gone because the demo is the page);
//   * the whole page stays short (a ceiling on the scroll height);
//   * what the page must keep is there, and what was removed does not return;
//   * nothing scrolls sideways, touch targets are 44 px, and axe is clean.

const MESSAGES = { es: esMessages, en: enMessages, fr: frMessages } as const;
const LOCALES = ["es", "en", "fr"] as const;

const PHONE = { width: 390, height: 844 }; // iPhone 12-15
const SE = { width: 375, height: 667 }; // the tightest common phone

// Total scroll height at 390 px, in CSS px. Measured 2,364 before the one-screen
// composition and 2,111 after (the old separate demo page added 1,278 more);
// the ceiling guards against a section quietly growing back.
const HEIGHT_CEILING = 2_250;

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
      test(`first screen ${viewport.width}x${viewport.height} ${locale}: headline, question and send, whole`, async ({
        browser,
      }) => {
        const m = MESSAGES[locale].home;
        const { context, page } = await phone(browser, viewport);
        await page.goto(`/${locale}`);

        await expect(page.getByRole("heading", { level: 1 })).toHaveText(m.calmTitle);

        const field = page.locator("#demo-question");
        const send = page.getByRole("button", { name: MESSAGES[locale].demo.askCta, exact: true });
        const start = page.getByRole("link", { name: m.cta, exact: true }).first();
        for (const [name, el] of [["field", field], ["send", send], ["start", start]] as const) {
          await expect(el, `${name}`).toBeVisible();
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
    test(`${locale}: short page, with the question, the sources, the price and the legal footer`, async ({
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

      // The static "one real answer" figure (proofAnswer) was removed: the live
      // answer to a suggested question is the proof now.
      await expect(page.getByTestId("demo-ask")).toBeVisible();
      await expect(page.getByTestId("demo-record").getByText(MESSAGES[locale].demo.badge, { exact: true })).toBeVisible();
      // Secondary information is deliberately closed in the phone-first design.
      await expect(page.locator("#pricing")).toBeHidden();
      await page.getByTestId("home-about").locator("summary").click();
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
      await page.getByTestId("home-about").locator("summary").click();
      for (const id of ["evidence", "pricing"]) {
        await expect(page.locator(`section#${id}`), `${locale}: #${id}`).toBeVisible();
      }
      await expect(page.getByRole("heading", { level: 2, name: m.evTitle })).toHaveCount(1);
      await context.close();
    }
  });
});
