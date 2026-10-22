import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";

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

const catalogs = { es, en, fr };
for (const locale of ["es", "en", "fr"] as const) {
  test(`live ${locale}: a grey example in the empty field, no obvious keyboard instructions`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/${locale}`);
    const field = page.locator("#demo-question");
    const placeholder = await field.getAttribute("placeholder");
    expect(placeholder).toBe(catalogs[locale].demo.askPlaceholder);
    // A concrete example, not another invitation, and not a copy of a suggestion.
    expect(placeholder).toMatch(/^(Por ejemplo|For example|Par exemple)/);
    for (const suggestion of await page.locator('[data-testid="demo-ask"] ul button').allInnerTexts()) {
      expect(suggestion).not.toContain(placeholder!.split(":")[1].trim().slice(0, 20));
    }
    const colors = await field.evaluate((el) => ({
      placeholder: getComputedStyle(el, "::placeholder").color,
      text: getComputedStyle(el).color,
    }));
    expect(colors.placeholder).not.toBe(colors.text);
    await expect(page.getByText(catalogs[locale].demo.uxKeyboard)).toHaveCount(0);
  });

  test(`live ${locale}: the logo returns home from an answer, and the page says it is a demo`, async ({ page }) => {
    await page.route("**/api/demo/ask", (route) => route.fulfill({ json: {
      kind: "answer", answer: "Texto de prueba [ev_1].", evidence_citations: [], disclaimer: "Aviso.",
    } }));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/${locale}`);
    const header = page.locator("header").first();
    await expect(header.getByText(catalogs[locale].demo.badge, { exact: true })).toBeVisible();
    await page.locator("#demo-question").fill("Pregunta de prueba");
    await page.locator('[data-testid="demo-ask"] button[type="submit"]').click();
    await expect(page.getByTestId("demo-answer")).toBeVisible();
    const logo = header.getByRole("link", { name: "AdelIA", exact: true });
    expect((await logo.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await logo.click();
    await expect(page.getByTestId("demo-answer")).toHaveCount(0);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator("#demo-question")).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/${locale}/?$`));
  });
}

const pediatrician = { es: /pediatra/, en: /pediatrician/, fr: /pédiatre/ };
for (const locale of ["es", "en", "fr"] as const) {
  test(`live ${locale}: the first screen says what AdelIA is and keeps the field in reach`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/${locale}`);
    const m = catalogs[locale];
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(m.home.calmTitle);
    // What it is, where answers come from, and that it does not replace the doctor.
    expect(m.home.calmTitle).toMatch(/IA|AI/);
    const intro = page.getByTestId("home-intro");
    await expect(intro).toHaveText(m.home.calmIntro);
    expect(m.home.calmIntro).toMatch(pediatrician[locale]);
    const field = (await page.locator("#demo-question").boundingBox())!;
    expect(field.y + field.height).toBeLessThanOrEqual(380);
  });

  test(`live ${locale}: source passages are not presented as literal quotations`, async ({ page }) => {
    // The corpus stores paraphrased summaries of each source (see the _meta
    // caveat in apps/api/adelia/enrichment/data). Calling them literal is false.
    const m = catalogs[locale];
    expect(m.demo.uxLiteralPassage).not.toMatch(/literal|littéral/i);
    await page.route("**/api/demo/ask", (route) => route.fulfill({ json: {
      kind: "answer", answer: "Texto [ev_1].", disclaimer: "Aviso.",
      evidence_citations: [{ tag: "ev_1", source_id: "s", chunk_id: "c", title: "Fuente", organization: "Org",
        year: 2026, url: "https://example.org", snippet: "Resumen de prueba." }],
    } }));
    await page.goto(`/${locale}`);
    await page.locator("#demo-question").fill("Pregunta de prueba");
    await page.locator('[data-testid="demo-ask"] button[type="submit"]').click();
    const depth = page.getByTestId("answer-depth");
    await depth.locator(":scope > summary").click();
    const source = depth.locator("details").first();
    await expect(source.locator("summary")).toContainText(m.demo.uxLiteralPassage);
    await source.locator("summary").click();
    await expect(source.locator("blockquote")).toHaveText("Resumen de prueba.");
  });
}
