import { expect, test } from "@playwright/test";
import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";

// Observable product-method rules, not a claim of clinical validation.
const messages = { es, en, fr };
for (const locale of ["es", "en", "fr"] as const) {
  for (const width of [375, 390, 430]) {
    test(`${locale}/${width}: calm welcome, progressive examples, honest demo, secondary details optional`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`/${locale}`);
      const m = messages[locale];
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(m.home.calmTitle);
      expect(m.home.calmIntro).not.toMatch(/ficti|10[.,]8|h[eé]moglob|haemoglob/i);
      const field = page.locator("#demo-question");
      const submit = page.getByRole("button", { name: m.demo.askCta, exact: true });
      for (const element of [field, submit]) {
        const box = (await element.boundingBox())!;
        expect(box.height).toBeGreaterThanOrEqual(43.9);
        expect(box.y + box.height).toBeLessThanOrEqual(844);
      }
      expect(await field.evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
      await expect(page.locator('[data-testid="demo-ask"] ul button:visible')).toHaveCount(3);
      await expect(page.locator('[data-testid="demo-ask"] ul button').first().locator('strong')).toBeVisible();
      expect(await field.getAttribute("placeholder")).not.toBe(await page.locator('[data-testid="demo-ask"] ul button strong').innerText());
      await expect(page.locator("#pricing")).toBeHidden();
      await expect(page.locator("#evidence")).toBeHidden();
      await expect(page.getByTestId("demo-record").getByText(m.demo.badge, { exact: true })).toBeVisible();
      await expect(page.locator('[data-testid="demo-ask"] ul button:visible')).toHaveCount(3);
      await page.getByTestId("home-about").locator("summary").click();
      await expect(page.locator("#pricing")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    });
  }
}
