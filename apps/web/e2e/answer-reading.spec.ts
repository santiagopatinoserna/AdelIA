import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";
import type { AnswerSourceContext as SourceContextType } from "@/components/answer-content";
import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";

// These responses exercise presentation only, not the model or clinical correctness.
test.use({ viewport: { width: 390, height: 844 } });
const shots = join(homedir(), "dev/adelia-design/shots/answer-reading");
const disclaimer = "AdelIA no sustituye a tu pediatra. Verifica con tu médico antes de tomar decisiones clínicas.";
const citation = {
  tag: "ev_1", source_id: "source-1", chunk_id: "chunk-1",
  title: "Documento de referencia: título completo", organization: "Organización de referencia",
  year: 2026, url: "https://example.org/source", snippet: "Pasaje literal de la fuente de prueba.",
};

async function answerWith(page: Page, answer: string, kind = "answer", withSources = true) {
  await page.route("**/api/demo/ask", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ kind, answer, evidence_citations: withSources ? [citation] : [], disclaimer }),
  }));
  await page.goto("/es");
  await page.locator("#demo-question").fill("¿Qué aparece en su historia?");
  await page.getByRole("button", { name: "Preguntar", exact: true }).click();
  await expect(page.getByTestId("demo-answer")).toBeVisible();
}

async function screenshot(page: Page, name: string) {
  await mkdir(shots, { recursive: true });
  await page.getByTestId("demo-answer").scrollIntoViewIfNeeded();
  console.log(`${name}: ${await page.getByTestId("demo-answer").innerText()}`);
  // Exclude only Next's development overlay from evidence, never product content.
  await page.screenshot({
    path: join(shots, `${name}.png`), fullPage: true,
    style: "nextjs-portal { display: none !important; }",
  });
}

test("renders supplied Markdown headings, emphasis and lists without losing citation markers", async ({ page }) => {
  await answerWith(page, "## Su historia\n\nEn el documento consta **una revisión** [1].\n\n- Primera anotación [ev_1].\n- Segunda anotación.\n\n### Próximas anotaciones\n\n1. Texto del documento.\n2. Otra anotación.");
  const answer = page.getByTestId("demo-answer");
  await expect(answer.getByRole("heading", { name: "Su historia", level: 3 })).toBeVisible();
  await expect(answer.locator("strong")).toHaveText("una revisión");
  await expect(answer.locator("ul > li")).toHaveText(["Primera anotación [ev_1].", "Segunda anotación."]);
  await expect(answer.locator("ol > li")).toHaveText(["Texto del documento.", "Otra anotación."]);
  await expect(answer.getByRole("heading", { name: "Próximas anotaciones", level: 4 })).toBeVisible();
  await expect(answer.getByText("En el documento consta una revisión [1].", { exact: true })).toBeVisible();
  for (const element of await answer.locator("p, li").all()) {
    // Sources and the fixed disclaimer have their existing secondary type scale.
    if (!(await element.innerText()).match(/anotación|documento consta|Texto del documento/)) continue;
    expect(await element.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
  }
  const accessibility = await new AxeBuilder({ page })
    .include('[data-testid="demo-answer"]').analyze();
  expect(accessibility.violations).toEqual([]);
  await screenshot(page, "markdown-phone");
});

test("attributes an answer to history only when numeric record references are present", async ({ page }) => {
  await answerWith(page, "El documento recoge esta anotación [1]. La fuente la contextualiza [ev_1].");
  const context = page.getByTestId("answer-source-context");
  await expect(context).toContainText("Esta respuesta relaciona el historial de Lucía con las fuentes citadas.");
  await expect(context).toContainText("guías clínicas, estudios o páginas de asociaciones pediátricas");
  await expect(context).toContainText("consultar el original");
});

test("shows dynamic library totals separately from sources used, and omits absent totals", async ({ page }) => {
  // Compile the actual component with React's runtime: Playwright's default
  // JSX transform creates component-test descriptors, not server-renderable JSX.
  const sourcePath = join(__dirname, "../components/answer-content.tsx");
  const compiled = ts.transpileModule(readFileSync(sourcePath, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const componentModule = { exports: {} as { AnswerSourceContext: typeof SourceContextType } };
  new Function("require", "module", "exports", compiled)(
    createRequire(sourcePath), componentModule, componentModule.exports,
  );
  const { AnswerSourceContext } = componentModule.exports;
  for (const [locale, messages, label] of [
    ["es", es, "Biblioteca completa"],
    ["en", en, "Full library"],
    ["fr", fr, "Bibliothèque complète"],
  ] as const) {
    for (const corpusStats of [{ sources: 8, chunks: 21 }, { sources: 42, chunks: 96 }, undefined]) {
      const markup = renderToStaticMarkup(createElement(NextIntlClientProvider, {
        locale, messages, timeZone: "UTC",
        children: createElement(AnswerSourceContext, {
          kind: "answer", answer: "Texto [ev_1].", corpusStats,
        }),
      }));
      await page.setContent(markup);
      const totals = page.getByTestId("answer-library-total");
      if (corpusStats) {
        await expect(totals).toContainText(label);
        await expect(totals).toContainText(String(corpusStats.sources));
        await expect(totals).toContainText(String(corpusStats.chunks));
      } else {
        await expect(totals).toHaveCount(0);
      }
    }
  }
});

test("does not claim history without numeric references or sources", async ({ page }) => {
  await answerWith(page, "Texto de referencia [ev_1].");
  const context = page.getByTestId("answer-source-context");
  await expect(context).toContainText("Esta respuesta se apoya en las fuentes citadas.");
  await expect(context).not.toContainText("historial");
  await answerWith(page, "Texto del documento [1].", "answer", false);
  await expect(page.getByTestId("answer-source-context")).toHaveCount(0);
  await expect(page.getByTestId("answer-library-total")).toHaveCount(0);
});

for (const kind of ["no_evidence", "evidence_only", "red_flag"]) {
  test(`never implies a composed, sourced answer for ${kind}`, async ({ page }) => {
    const original = "Mensaje original completo de prueba [1] [ev_1].";
    await answerWith(page, original, kind);
    await expect(page.getByTestId("answer-source-context")).toHaveCount(0);
    await expect(page.getByTestId("answer-library-total")).toHaveCount(0);
    await expect(page.getByTestId("demo-answer").getByText(disclaimer, { exact: true })).toBeVisible();
    if (kind === "evidence_only") {
      await expect(page.getByTestId("answer-content")).toHaveText(es.demo.evidenceOnlyNote);
    } else {
      await expect(page.getByTestId("answer-content")).toHaveText(original);
    }
  });
}

test("keeps plain paragraphs verbatim without inventing headings or clinical structure", async ({ page }) => {
  const paragraphs = [
    "En la revisión figura el peso anotado [1].\nEsta es la siguiente línea del documento.",
    "No consta otra medición en los documentos disponibles [ev_1].",
  ];
  await answerWith(page, paragraphs.join("\n\n"));
  const content = page.getByTestId("answer-content");
  await expect(content.locator(":scope > p")).toHaveText(paragraphs, { useInnerText: false });
  expect(await content.locator("p").allTextContents()).toEqual(paragraphs);
  await expect(content.locator("h1,h2,h3,h4,h5,h6,ul,ol,strong,details")).toHaveCount(0);
  const styles = await content.locator("p").evaluateAll((elements) => elements.map((el) => {
    const style = getComputedStyle(el);
    return { size: parseFloat(style.fontSize), line: parseFloat(style.lineHeight) };
  }));
  for (const style of styles) {
    expect(style.size).toBeGreaterThanOrEqual(16);
    expect(style.line).toBeGreaterThanOrEqual(24);
    expect(style.line).toBeLessThanOrEqual(30);
  }
  await expect(page.getByTestId("demo-answer").getByText(disclaimer, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await screenshot(page, "paragraphs-phone");
});

test("does not execute raw HTML or javascript links from an answer", async ({ page }) => {
  await answerWith(page, 'Texto [ev_1] y [1].\n\n<script>window.answerInjected=true</script>\n\n<img src=x onerror="window.answerInjected=true">\n\n[Enlace inseguro](javascript:alert%281%29) y [documento](https://example.org/source).');
  const content = page.getByTestId("answer-content");
  await expect(content.locator("script,img,[onerror],[onclick]")).toHaveCount(0);
  await expect(content.locator('a[href^="javascript:"]')).toHaveCount(0);
  expect(await page.evaluate(() => "answerInjected" in window)).toBe(false);
  await expect(content.getByRole("link", { name: "documento", exact: true })).toHaveAttribute("href", "https://example.org/source");
  await expect(content).toContainText("Texto [ev_1] y [1].");
});

test("keeps the entire red-flag response, notice, disclaimer and expandable source", async ({ page }) => {
  const text = "Texto de derivación completo de prueba.\n\nSegunda indicación del mensaje original [ev_1].";
  await answerWith(page, text, "red_flag");
  const answer = page.getByTestId("demo-answer");
  expect(await page.getByTestId("answer-content").locator("p").allTextContents()).toEqual(text.split("\n\n"));
  await expect(answer.getByText(/No puedo valorar a tu bebé a distancia/)).toBeVisible();
  await expect(answer.getByText(disclaimer, { exact: true })).toBeVisible();
  const source = answer.locator("details");
  await expect(source).not.toHaveAttribute("open");
  await source.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(source).toHaveAttribute("open", "");
  await expect(source.locator("blockquote")).toHaveText(`“${citation.snippet}”`);
  await expect(source.getByRole("link")).toHaveAttribute("href", citation.url);
  await screenshot(page, "red-flag-source-phone");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await screenshot(page, "red-flag-source-desktop");
});
