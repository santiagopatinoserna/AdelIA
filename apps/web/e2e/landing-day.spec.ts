import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { openLandingFold } from "./utils/landing";

// Public landing, section "Un día con AdelIA" (#day): five moments of a
// parent's day, each showing the artefact the product produces. No login,
// no external calls. Copy comes from messages/*.json home.day.*.

const STEP_TIMES = ["08:50", "13:00", "17:30", "21:00"];

test.describe("landing: Un día con AdelIA", () => {
  test("shows the five moments with their artefacts and one CTA", async ({ page }) => {
    await page.goto("/es");
    const day = page.locator("section#day");
    await expect(day).toBeVisible();
    await expect(day.getByRole("heading", { level: 2, name: "Un día con AdelIA" })).toBeVisible();

    for (const time of STEP_TIMES) {
      await expect(day.getByText(time, { exact: true }).first()).toBeVisible();
    }
    // The artefacts, not descriptions: bot reply, extracted data, essentials,
    // cited answer, briefing.
    await expect(day.getByText("Guardado en el diario de Adel ✓")).toBeVisible();
    await expect(day.getByText("3 datos extraídos")).toBeVisible();
    await expect(day.getByText("Lo esencial", { exact: true })).toBeVisible();
    await expect(day.getByText("¿Es normal que con 13 meses solo quiera leche materna?")).toBeVisible();
    await expect(day.getByText("Briefing para la pediatra")).toBeVisible();
    // Every artefact is labelled as an example: no false "generated" claims.
    await expect(day.getByText("generado con AdelIA")).toHaveCount(0);

    const cta = day.getByRole("link", { name: "Empezar con mi bebé" });
    await expect(cta).toBeVisible();
    await cta.click();
    // Without a session the dashboard redirects to sign-in.
    await expect(page).toHaveURL(/\/es\/(dashboard|signin)/, { timeout: 20_000 });
  });

  // Audit 1.2: the medical notice used to live only in the page footer, far from the fever
  // and paracetamol the block talks about. It now sits inside #day, ahead of the first step,
  // at reading size (the 11px footnote under the CTA stays a statement about the data).
  const NOTICE: Record<string, RegExp> = {
    es: /no sustituye el consejo médico/,
    en: /does not replace medical advice/,
    fr: /ne remplace pas l’avis médical/,
  };

  for (const locale of ["es", "en", "fr"]) {
    test(`carries its own medical notice before the first step (${locale})`, async ({ page }) => {
      await page.goto(`/${locale}`);
      const day = page.locator("section#day");
      const note = day.getByTestId("day-disclaimer");
      await expect(note).toBeVisible();
      await expect(note).toContainText(NOTICE[locale]);
      await expect(note).toContainText("112");

      const noteBox = await note.boundingBox();
      const firstStepBox = await day.locator("ol > li").first().boundingBox();
      expect(noteBox, "notice has a box").not.toBeNull();
      expect(firstStepBox, "first step has a box").not.toBeNull();
      expect(noteBox!.y + noteBox!.height).toBeLessThanOrEqual(firstStepBox!.y);

      // Not small print: at least 14px.
      const fontSize = await note
        .locator("p")
        .evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
      expect(fontSize).toBeGreaterThanOrEqual(14);
    });
  }

  test("is accessible and never scrolls the body sideways, desktop and phone", async ({ browser }) => {
    for (const viewport of [
      { width: 1280, height: 800 },
      { width: 390, height: 844 },
    ]) {
      // The step cards enter with the ad-rise animation: sampling colors
      // mid-fade reads lighter text than the stylesheet declares and fails
      // contrast for the wrong reason. Reduced motion disables it.
      const context = await browser.newContext({
        viewport,
        isMobile: viewport.width < 500,
        hasTouch: viewport.width < 500,
        reducedMotion: "reduce",
      });
      const page = await context.newPage();
      await page.goto("/es");
      // On a phone #day is folded behind "Ver más" (components/landing-fold.tsx,
      // the 11,936 px landing). Open it first, so axe and the overflow check
      // below still see the whole section; the assertions are unchanged.
      if (viewport.width < 500) await openLandingFold(page);
      await expect(page.locator("section#day")).toBeVisible();
      const results = await new AxeBuilder({ page }).include("#day").analyze();
      expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `horizontal overflow at ${viewport.width}px`).toBeLessThanOrEqual(0);
      await context.close();
    }
  });
});
