import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

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

  test("is accessible and never scrolls the body sideways, desktop and phone", async ({ browser }) => {
    for (const viewport of [
      { width: 1280, height: 800 },
      { width: 390, height: 844 },
    ]) {
      const context = await browser.newContext({ viewport, isMobile: viewport.width < 500, hasTouch: viewport.width < 500 });
      const page = await context.newPage();
      await page.goto("/es");
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
