import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser, type Page } from "@playwright/test";

import enMessages from "@/messages/en.json";
import esMessages from "@/messages/es.json";
import frMessages from "@/messages/fr.json";

import { openLandingFold } from "./utils/landing";

// The landing on a phone, for a mother who has the baby in one arm. What this
// pins, and what it deliberately leaves to other specs:
//
//   * the first screen holds the headline and both buttons, whole;
//   * the page stays short: a ceiling on the total scroll height;
//   * what is folded behind "Ver más" is still reachable (button, hash link);
//   * the desktop page is untouched, and the open phone page is accessible.
//
// Word clipping and touch heights of the PANEL are showcase.spec.ts and
// mobile.spec.ts. Sideways overflow of the open #day is landing-day.spec.ts.
// This file only adds what the landing needs and nothing there covers.

const MESSAGES = { es: esMessages, en: enMessages, fr: frMessages } as const;
const LOCALES = ["es", "en", "fr"] as const;

const PHONE = { width: 390, height: 844 }; // iPhone 12-15
const SE = { width: 375, height: 667 }; // the tightest common phone

// Total scroll height of the CLOSED page at 390 px, in CSS px.
//
//   2026-10-14, before the fold:  11,936 px  (about 14 screens of 844)
//   after, es / en / fr:           2,436 / 2,390 / 2,488 px
//
// 2,800 px (about 3.3 screens) is 12 % above the worst locale: room for copy to
// grow a little, not room for a section. The smallest folded block (the
// open-source band, ~540 px plus its 112 px gap) added to the worst locale
// already breaks it, so un-folding anything, or adding a card to the first
// screens, fails here and has to be argued for. Do not raise it to make a
// change fit: fold the change instead.
const CLOSED_HEIGHT_CEILING = 2_800;

// Blink reports a 2.75rem (44 px) box as 43.999969482421875 under mobile
// emulation; same epsilon and reason as showcase.spec.ts.
const EPS = 0.05;
const TAP_MIN = 44 - EPS;

// Air kept between the last button and the fold, so "visible" does not mean
// "touching the bottom edge". Measured: 306 px on 390x844, 93 px on 375x667.
const FOLD_AIR = 24;

async function phone(browser: Browser, viewport = PHONE, scheme: "light" | "dark" = "light") {
  // Reduced motion: the hero enters with a 14 px rise (ad-rise) and a box
  // measured mid-animation is not where the reader sees it settle.
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
      test(`first screen ${viewport.width}x${viewport.height} ${locale}: headline and both buttons, whole, no scroll`, async ({
        browser,
      }) => {
        const m = MESSAGES[locale].home;
        const { context, page } = await phone(browser, viewport);
        await page.goto(`/${locale}`);

        expect(await page.evaluate(() => window.scrollY), "starts at the top").toBe(0);

        const h1 = page.getByRole("heading", { level: 1 });
        await expect(h1).toBeInViewport({ ratio: 1 });

        // One "Empezar" on a phone: the header copy is hidden there (the hero
        // carries the same action on the same screen), and the strict-mode
        // locator below also fails if a second one shows up in the page.
        await expect(page.getByRole("banner").getByRole("link", { name: m.cta, exact: true })).toHaveCount(0);
        const start = page.getByRole("main").getByRole("link", { name: m.cta, exact: true });
        // Three links carry the demo name (hero, the closing one, the footer);
        // the hero's is first in the document.
        const demo = page.getByRole("link", { name: m.demoLink, exact: true }).first();
        for (const [name, link] of [
          ["start", start],
          ["demo", demo],
        ] as const) {
          await expect(link, `${name} fully inside the first screen`).toBeInViewport({ ratio: 1 });
          const box = await link.boundingBox();
          expect(box, name).not.toBeNull();
          expect(box!.height, `${name}: touch height`).toBeGreaterThanOrEqual(TAP_MIN);
          expect(box!.y + box!.height, `${name}: air above the fold`).toBeLessThanOrEqual(
            viewport.height - FOLD_AIR,
          );
        }

        // The two do not touch: spec 7.5, 8 px between adjacent touch targets.
        const a = (await start.boundingBox())!;
        const b = (await demo.boundingBox())!;
        expect(b.y - (a.y + a.height), "gap between the two buttons").toBeGreaterThanOrEqual(8);

        const w = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
        }));
        expect(w.scroll, "first screen scrolls sideways").toBe(w.client);
        await context.close();
      });
    }
  }

  for (const locale of LOCALES) {
    test(`${locale}: the closed page stays under ${CLOSED_HEIGHT_CEILING}px and the proof is in it`, async ({
      browser,
    }) => {
      const m = MESSAGES[locale].home;
      const { context, page } = await phone(browser);
      await page.goto(`/${locale}`);

      const height = await scrollHeight(page);
      expect(
        height,
        `closed landing is ${height}px tall at 390px; ceiling ${CLOSED_HEIGHT_CEILING}. Fold the change instead of raising the ceiling.`,
      ).toBeLessThanOrEqual(CLOSED_HEIGHT_CEILING);

      // What survives: the proof card, the evidence guarantee (one copy, the
      // phone one), the closing way in, and the footer with its disclaimer.
      await expect(page.getByRole("heading", { level: 2, name: m.evTitle })).toHaveCount(1);
      await expect(page.getByRole("heading", { level: 2, name: m.evTitle })).toBeVisible();
      const closing = page.getByRole("link", { name: m.demoLink, exact: true }).nth(1);
      await closing.scrollIntoViewIfNeeded();
      const closingBox = await closing.boundingBox();
      expect(closingBox!.height, "closing demo link: touch height").toBeGreaterThanOrEqual(TAP_MIN);
      await expect(page.getByRole("contentinfo")).toBeVisible();

      // What is folded: not displayed, so not in the way and not in the tab order.
      for (const id of ["day", "features", "how", "story", "pricing"]) {
        await expect(page.locator(`section#${id}`), `#${id} is folded`).toBeHidden();
      }
      const toggle = page.getByTestId("landing-fold-toggle");
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(toggle).toHaveText(m.foldMore);
      await toggle.scrollIntoViewIfNeeded();
      const toggleBox = await toggle.boundingBox();
      expect(toggleBox!.height, "fold toggle: touch height").toBeGreaterThanOrEqual(TAP_MIN);

      // The "Ver cómo funciona" button points at #how, which is folded: gone.
      await expect(page.getByRole("link", { name: m.ctaSecondary })).toHaveCount(0);
      await context.close();
    });
  }

  test("'Ver más' opens every folded section and 'Ver menos' closes them again", async ({
    browser,
  }) => {
    const m = esMessages.home;
    const { context, page } = await phone(browser);
    await page.goto("/es");
    await openLandingFold(page);

    const toggle = page.getByTestId("landing-fold-toggle");
    await expect(toggle).toHaveText(m.foldLess);
    for (const id of ["day", "features", "how", "story", "pricing"]) {
      await expect(page.locator(`section#${id}`), `#${id} opens`).toBeVisible();
    }
    // Nothing is shown twice: the phone copy of the evidence guarantee is the
    // only one displayed, the desktop copy (with the id) stays hidden.
    await expect(page.getByRole("heading", { level: 2, name: m.evTitle })).toHaveCount(1);
    await expect(page.locator("section#evidence")).toBeHidden();
    // The pricing section is what the reader came for: trial and no card.
    await expect(page.locator("section#pricing").getByText(m.prT2Trial)).toBeVisible();

    // Keyboard: the toggle is a real button and Enter closes it.
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.locator("section#day")).toBeHidden();
    await expect(toggle).toBeFocused();
    await context.close();
  });

  test("a link to a folded section (#pricing) opens the fold and lands on it", async ({
    browser,
  }) => {
    const { context, page } = await phone(browser);
    await page.goto("/es#pricing");
    const pricing = page.locator("section#pricing");
    await expect(pricing).toBeVisible();
    await expect(pricing).toBeInViewport();
    await expect(page.getByTestId("landing-fold-toggle")).toHaveAttribute("aria-expanded", "true");
    await context.close();
  });

  test("a11y: no serious or critical violation, fold closed and open, light and dark", async ({
    browser,
  }) => {
    for (const scheme of ["light", "dark"] as const) {
      const { context, page } = await phone(browser, PHONE, scheme);
      await page.goto("/es");
      await page.waitForLoadState("networkidle").catch(() => {});
      for (const state of ["closed", "open"] as const) {
        if (state === "open") await openLandingFold(page);
        const results = await new AxeBuilder({ page }).analyze();
        const blocking = results.violations.filter((v) =>
          ["serious", "critical"].includes(v.impact ?? ""),
        );
        expect(
          blocking,
          `${scheme}/${state}: ${blocking.map((v) => v.id).join(", ")}`,
        ).toEqual([]);
      }
      await context.close();
    }
  });
});

test.describe("landing on a desktop", () => {
  test("is the long page it was: no fold, every section, the secondary button", async ({
    browser,
  }) => {
    for (const locale of LOCALES) {
      const m = MESSAGES[locale].home;
      const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      const page = await context.newPage();
      await page.goto(`/${locale}`);

      await expect(page.getByTestId("landing-fold-toggle")).toBeHidden();
      for (const id of ["day", "features", "how", "story", "evidence", "pricing"]) {
        await expect(page.locator(`section#${id}`), `${locale}: #${id}`).toBeVisible();
      }
      // One evidence guarantee, in its original place; the phone copy is hidden.
      await expect(page.getByRole("heading", { level: 2, name: m.evTitle })).toHaveCount(1);
      const how = page.getByRole("link", { name: m.ctaSecondary });
      await expect(how).toBeVisible();
      await expect(how).toHaveAttribute("href", "#how");
      // The header's "Empezar" is back.
      await expect(page.getByRole("banner").getByRole("link", { name: m.cta, exact: true })).toBeVisible();
      await context.close();
    }
  });
});
