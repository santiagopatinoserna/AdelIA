import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const homeCss = readFileSync(path.join(root, "app/[locale]/home.module.css"), "utf8");
const homePage = readFileSync(path.join(root, "app/[locale]/page.tsx"), "utf8");

// Exercise the actual homepage CSS without rebuilding or replacing a shared server.
// This is a composition harness, not a substitute for the live-page checks below.
for (const width of [375, 390, 430]) {
  test(`composition: support follows a full question workspace at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 812 });
    await page.setContent(`
      <style>
        * { box-sizing: border-box; } body { margin: 0; }
        :root { --font-sans: sans-serif; --font-display: serif; }
        ${homeCss.replace(/:global\(([^)]+)\)/g, "$1")}
      </style>
      <div class="home">
        <header class="header">AdelIA</header>
        <main class="main">
          <div class="workspace">
            <section class="command"><h1 class="headline">¿Qué te preocupa hoy?</h1>
              <div class="ask"><textarea aria-label="Pregunta"></textarea>
              <button type="submit">Preguntar</button></div>
            </section>
            <div class="record"><details><summary>Su historia hasta hoy · Demo</summary></details></div>
          </div>
          <details class="support"><summary class="aboutToggle">Sobre AdelIA</summary></details>
        </main>
      </div>`);
    const bounds = await page.locator(".support").boundingBox();
    expect(bounds!.y).toBeGreaterThanOrEqual(812);
    const submit = await page.getByRole("button").boundingBox();
    expect(submit!.y + submit!.height).toBeLessThan(812);
    expect(submit!.height).toBeGreaterThan(44);
    expect(await page.locator(".aboutToggle").evaluate(el => parseFloat(getComputedStyle(el).fontSize)))
      .toBeGreaterThanOrEqual(16);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("composition: secondary controls are usable with one hand", async ({ page }) => {
  await page.setContent(`<style>${homeCss.replace(/:global\(([^)]+)\)/g, "$1")}</style>
    <div class="home"><header class="header"><a href="#">Entrar</a>
    <div class="home-language"><select aria-label="Idioma"><option>ES</option></select></div></header>
    <div class="record"><details><summary>Demo</summary></details></div>
    <div class="ask"><button>Ejemplo</button></div>
    <div class="footerInner"><nav><a href="#">Privacidad</a></nav></div></div>`);
  for (const control of await page.locator("a,select,summary,button").all()) {
    expect((await control.boundingBox())!.height).toBeGreaterThan(44);
  }
});

test("composition: data handling is disclosed before optional product information", () => {
  expect(homePage.indexOf('t("demo.noStore")'))
    .toBeLessThan(homePage.indexOf('data-testid="home-about"'));
});

test("composition: clinical footer stays outside optional product information", () => {
  const supportEnd = homePage.indexOf("</details>");
  expect(homePage.indexOf('t("home.footerDisclaimer")')).toBeGreaterThan(supportEnd);
  expect(homePage).toContain('t("demo.noStore")');
  expect(homePage).toContain('t("home.footerPrivacy")');
  expect(homePage).toContain('t("home.footerTerms")');
});

for (const width of [375, 390, 430]) {
  test(`live: question first, transparent optional history at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 812 });
    await page.goto("/es");
    const ask = page.getByTestId("demo-ask");
    const field = ask.locator("textarea");
    const submit = ask.locator('button[type="submit"]');
    await expect(field).toBeInViewport({ ratio: 1 });
    await expect(submit).toBeInViewport({ ratio: 1 });
    expect((await submit.boundingBox())!.height).toBeGreaterThan(44);
    const record = page.getByTestId("demo-record");
    await expect(record).not.toHaveAttribute("open");
    await expect(record.locator("summary")).toContainText("Demo");
    await expect(record.locator("summary")).toContainText("Lucía");
    const about = page.getByTestId("home-about");
    await expect(about).not.toHaveAttribute("open");
    expect((await about.boundingBox())!.y).toBeGreaterThanOrEqual(812);
    await record.locator("summary").click();
    await expect(record).toContainText("creada para que puedas probar AdelIA");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
