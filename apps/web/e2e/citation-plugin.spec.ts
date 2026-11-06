import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";
import ts from "typescript";

import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";

// Unit tests of the citation-marker plugin in components/answer-content.tsx,
// compiled with a plain require like answer-reading.spec.ts does. The marker
// is drawn as a number, but the model's text must come out of the renderer
// character for character (prod journey 2026-11-06).

type Module = typeof import("../components/answer-content");
const sourcePath = join(__dirname, "../components/answer-content.tsx");
function load(): Module {
  const compiled = ts.transpileModule(readFileSync(sourcePath, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const mod = { exports: {} as Module };
  new Function("require", "module", "exports", compiled)(createRequire(sourcePath), mod, mod.exports);
  return mod.exports;
}
const { AnswerContent, parseMarker, findCiteTarget } = load();

function render(text: string, { locale = "es", recordLinks = false } = {}) {
  const messages = { es, en, fr }[locale as "es" | "en" | "fr"];
  return renderToStaticMarkup(createElement(NextIntlClientProvider, {
    locale, messages, timeZone: "Europe/Madrid",
    children: createElement(AnswerContent, { recordLinks, children: text }),
  }));
}

const visibleText = (html: string) => html.replace(/<[^>]+>/g, "").replace(/&amp;/g, "&");

test("parseMarker: a source keeps its tag, a record becomes rec_N", () => {
  expect(parseMarker("[ev_12]")).toEqual({ inner: "ev_12", kind: "ev", n: "12", key: "ev_12" });
  expect(parseMarker("[ex_1]")).toEqual({ inner: "ex_1", kind: "ex", n: "1", key: "ex_1" });
  expect(parseMarker("[3]")).toEqual({ inner: "3", kind: "rec", n: "3", key: "rec_3" });
});

test("an evidence marker acts as a button named 'Fuente N' and keeps the literal marker", () => {
  const html = render("Que la piel quede limpia y seca [ev_1][ev_2].");
  expect(html).toContain(
    '<span class="ad-cite ad-cite-ev" data-cite="ev_1" data-n="1" aria-label="Fuente 1" role="button" tabindex="0">'
    + '<span class="ad-cite-raw">[ev_1]</span></span>',
  );
  // Never a <button> element: under the demo answer a visible button in a
  // list means a suggestion came back (mother-first-answer.spec.ts).
  expect(html).not.toContain("<button");
  expect(html).toContain('data-cite="ev_2" data-n="2" aria-label="Fuente 2"');
  // Presentation only: the text the model wrote, verbatim.
  expect(visibleText(html)).toBe("Que la piel quede limpia y seca [ev_1][ev_2].");
});

test("experience and record markers are drawn apart from evidence", () => {
  const html = render("Una toma a las 17:00 [2]. Otras madres lo cuentan [ex_1].", { recordLinks: true });
  expect(html).toContain('class="ad-cite ad-cite-rec" data-cite="2" data-n="2" aria-label="Historial 2" role="button" tabindex="0"');
  expect(html).toContain('class="ad-cite ad-cite-ex" data-cite="ex_1" data-n="1" aria-label="Fuente 1" role="button" tabindex="0"');
});

test("a record marker with no card on the page is not a dead button", () => {
  const html = render("Consta una revisión [1].");
  expect(html).toContain('<span class="ad-cite ad-cite-rec" data-cite="1" data-n="1" aria-label="Historial 1" role="img">');
  expect(html).not.toContain('role="button"');
});

test("a marker inside a link is never a button within a link", () => {
  const html = render("Mira [la guía [ev_1]](https://example.org/guia).");
  expect(html).toMatch(/<a [^>]*href="https:\/\/example.org\/guia"[^>]*>la guía <span class="ad-cite ad-cite-ev"[^>]*role="img"/);
  expect(html).not.toContain('role="button"');
});

test("code and plan headings keep their text; nothing else looks like a marker", () => {
  const html = render(`Texto [nota] y \`[ev_1]\` en código [ev_1].\n\n## ${es.demo.plan.today}\n- Acción [ev_3].`);
  expect(html).toContain("<code>[ev_1]</code>");
  expect(html).toContain("[nota]");
  expect((html.match(/data-cite=/g) ?? []).length).toBe(2);
  expect(html).toContain('data-cite="ev_3"');
});

test("the screen-reader word follows her language", () => {
  for (const [locale, source, record] of [["en", "Source", "History"], ["fr", "Source", "Historique"]] as const) {
    const html = render("A [ev_1] and [2].", { locale, recordLinks: true });
    expect(html).toContain(`aria-label="${source} 1"`);
    expect(html).toContain(`aria-label="${record} 2"`);
  }
});

test("findCiteTarget picks the card after this answer, never an earlier answer's", async ({ page }) => {
  await page.setContent(`
    <div data-testid="answer-content" id="a1"><span role="button" data-cite="ev_1">1</span></div>
    <div data-cite-target="ev_1" id="card-a1"></div>
    <div data-testid="answer-content" id="a2"><span role="button" data-cite="ev_1">1</span><span role="button" data-cite="ev_2">2</span></div>
    <div data-cite-target="ev_1" id="card-a2"></div>
    <div data-testid="answer-content" id="a3"></div>
    <div data-cite-target="ev_2" id="card-a3"></div>`);
  await page.addScriptTag({ content: `window.findCiteTarget = ${findCiteTarget.toString()}` });
  const pick = (answer: string, key: string) => page.evaluate(([a, k]) => {
    const fn = (window as unknown as { findCiteTarget: (r: HTMLElement, k: string) => HTMLElement | null }).findCiteTarget;
    return fn(document.getElementById(a)!, k)?.id ?? null;
  }, [answer, key]);
  expect(await pick("a1", "ev_1")).toBe("card-a1");
  expect(await pick("a2", "ev_1")).toBe("card-a2");
  // ev_2 has a card only under the third answer: the second must not borrow it.
  expect(await pick("a2", "ev_2")).toBeNull();
});
