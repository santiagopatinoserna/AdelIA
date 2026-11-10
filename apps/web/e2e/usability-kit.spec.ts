import { expect, test } from "@playwright/test";
import { join } from "node:path";

import ciConfig from "../playwright.config";
import smokeConfig from "../e2e-prod/playwright.config";
import usabilityConfig from "../e2e-prod/usability/playwright.config";
import budgets from "../e2e-prod/usability/budgets.json";
import fixtures from "../e2e-prod/usability/fixtures.json";
import { QA_HEADERS } from "../e2e-prod/kit";
import {
  KEYBOARD_HEIGHT,
  LOCALES,
  PERF_LIMITS,
  SCHEMES,
  VIEWPORTS,
  budgetKey,
  type Issue,
  journeyTotals,
  median,
  overBudget,
  perfIssues,
  rankIssues,
  renderReport,
  smallTargets,
  stubTurnFor,
  usabilitySettings,
} from "../e2e-prod/usability/kit";

// The usability battery (e2e-prod/usability/) runs against the live site like
// the smoke suite, so the parts that decide what it measures, what counts as
// a problem and how the report orders them are pinned here, in CI, with no
// server. The battery never makes a model answer: it sends only the smoke
// suite's red flags, and the plan and the clarify card it reads are answered
// inside the browser from fixtures.json (stubTurnFor).

const NOW = new Date(2026, 10, 10, 3, 4, 5);

test("settings: the live site by default, its own run folder under the home folder", () => {
  const s = usabilitySettings({}, { home: "/home/hermes", now: NOW });
  expect(s.baseURL).toBe("https://adelia.godi.ai");
  expect(s.runDir).toBe(
    join("/home/hermes", "dev/adelia-design/shots/usability", "2026-11-10_03-04-05"),
  );
  const local = usabilitySettings(
    { PROD_SMOKE_URL: "http://localhost:3118/", USABILITY_RUN_DIR: "/tmp/u1", PW_CHANNEL: "chrome" },
    { home: "/home/hermes", now: NOW },
  );
  expect(local).toEqual({ baseURL: "http://localhost:3118", channel: "chrome", runDir: "/tmp/u1" });
});

test("the battery runs alone: one worker, the QA header, never in CI or in the smoke run", () => {
  expect(usabilityConfig.workers).toBe(1);
  expect(usabilityConfig.fullyParallel).toBe(false);
  expect(usabilityConfig.use?.extraHTTPHeaders).toEqual(QA_HEADERS);
  expect(usabilityConfig.use?.serviceWorkers).toBe("block");
  expect(ciConfig.testDir).toBe("./e2e");
  expect(smokeConfig.testIgnore).toEqual(["usability/**"]);
});

test("the matrix: 360, 390, 430 and a tablet, light and dark, es/en/fr", () => {
  expect(VIEWPORTS.map((v) => v.width)).toEqual([360, 390, 430, 768]);
  expect(VIEWPORTS.filter((v) => v.phone).map((v) => v.name)).toEqual(["360", "390", "430"]);
  expect([...SCHEMES]).toEqual(["light", "dark"]);
  expect([...LOCALES]).toEqual(["es", "en", "fr"]);
  // A phone keyboard takes roughly 40 % of the height; what is left must
  // still hold the field.
  for (const v of VIEWPORTS) {
    const kb = KEYBOARD_HEIGHT(v);
    expect(kb).toBeGreaterThan(v.height * 0.3);
    expect(kb).toBeLessThan(v.height * 0.5);
  }
});

test("a first screen may not grow: any of blocks, taps or words over its budget fails", () => {
  const budget = { blocks: 10, taps: 5, words: 60 };
  expect(overBudget({ blocks: 10, taps: 5, words: 60 }, budget, "panel.390.es")).toEqual([]);
  expect(overBudget({ blocks: 9, taps: 4, words: 40 }, budget, "panel.390.es")).toEqual([]);
  expect(overBudget({ blocks: 11, taps: 6, words: 61 }, budget, "panel.390.es")).toEqual([
    "panel.390.es: blocks 11 > 10",
    "panel.390.es: taps 6 > 5",
    "panel.390.es: words 61 > 60",
  ]);
  expect(overBudget({ blocks: 1, taps: 1, words: 1 }, undefined, "x.360.fr")).toEqual([
    "x.360.fr: no budget recorded",
  ]);
  expect(budgetKey("thread", VIEWPORTS[0], "fr")).toBe("thread.360.fr");
});

test("budgets.json has a budget for every page, phone or tablet width and language", () => {
  for (const page of ["landing", "panel", "thread"]) {
    for (const v of VIEWPORTS) {
      for (const locale of LOCALES) {
        const b = (budgets as Record<string, { blocks: number; taps: number; words: number }>)[
          budgetKey(page, v, locale)
        ];
        expect(b, budgetKey(page, v, locale)).toBeTruthy();
        expect(b.blocks).toBeGreaterThan(0);
        expect(b.taps).toBeGreaterThan(0);
        expect(b.words).toBeGreaterThan(0);
      }
    }
  }
});

test("tap targets: under 44 px in either side is small, a link inside a sentence is exempt", () => {
  const small = smallTargets([
    { name: "Grabar", x: 0, y: 0, width: 120, height: 44, inline: false },
    { name: "Enviar", x: 0, y: 0, width: 43.5, height: 44, inline: false },
    { name: "Más", x: 0, y: 0, width: 200, height: 30, inline: false },
    { name: "privacidad", x: 0, y: 0, width: 60, height: 20, inline: true },
    // Sub-pixel rounding of a 44 px box is still 44 px.
    { name: "Ajustes", x: 0, y: 0, width: 72, height: 43.98, inline: false },
  ]);
  expect(small.map((t) => t.name)).toEqual(["Enviar", "Más"]);
});

test("issues are ranked by what bothers a mother with a baby in her arms most, then by reach", () => {
  const issues: Issue[] = [
    { kind: "budget", where: "panel.390.es", detail: "words 70 > 60" },
    { kind: "small-target", where: "panel.360.es.light", detail: "«Más» 200x30" },
    { kind: "small-target", where: "panel.390.es.light", detail: "«Más» 200x30" },
    { kind: "safety-hidden", where: "plan.390.fr.dark", detail: "«Quand consulter» below the fold" },
    { kind: "control-covered", where: "landing.360.es.light", detail: "consent-banner covers «Preguntar»" },
    { kind: "slow", where: "landing", detail: "LCP 5200 ms > 4000 ms" },
    { kind: "small-target", where: "settings.390.es.light", detail: "«x» 30x30" },
  ];
  const ranked = rankIssues(issues);
  expect(ranked.map((r) => r.kind)).toEqual([
    "safety-hidden",
    "control-covered",
    "small-target",
    "small-target",
    "slow",
    "budget",
  ]);
  // The same problem in two places is one line that says where.
  expect(ranked[2]).toMatchObject({ detail: "«Más» 200x30", count: 2 });
  expect(ranked[2].where).toEqual(["panel.360.es.light", "panel.390.es.light"]);
  expect(ranked[0].label).toMatch(/médico|urgencia|aviso/i);
});

test("performance: the median of the samples against fixed limits, per page", () => {
  expect(median([3, 1, 2])).toBe(2);
  expect(median([4, 1, 3, 2])).toBe(2.5);
  expect(PERF_LIMITS.landing.lcpMs).toBeGreaterThan(0);
  expect(PERF_LIMITS.panel.typeMs).toBeGreaterThan(0);
  const ok = { lcpMs: 100, typeMs: 100, jsKB: 10 };
  expect(perfIssues("landing", ok)).toEqual([]);
  const slow = {
    lcpMs: PERF_LIMITS.landing.lcpMs + 1,
    typeMs: PERF_LIMITS.landing.typeMs + 1,
    jsKB: PERF_LIMITS.landing.jsKB + 1,
  };
  expect(perfIssues("landing", slow).map((i) => i.kind)).toEqual(["slow", "slow", "heavy"]);
  expect(perfIssues("landing", slow)[0].detail).toMatch(/^LCP \d+ ms > \d+ ms$/);
});

test("a journey adds up its taps and its time, step by step", () => {
  const t = journeyTotals([
    { name: "portada", taps: 1, ms: 1200, ok: true },
    { name: "urgencia", taps: 2, ms: 3000, ok: true },
    { name: "borrar", taps: 3, ms: 900, ok: false },
  ]);
  expect(t).toEqual({ taps: 6, ms: 5100, ok: false, failed: ["borrar"] });
});

test("the stubbed turns: a plan and a clarify round per language, answered in the browser", () => {
  for (const locale of LOCALES) {
    const plan = stubTurnFor({ message: fixtures.plan[locale].message, locale });
    expect(plan).not.toBeNull();
    expect(plan!).toContain("event: token");
    expect(plan!).toContain("event: final");
    const clarify = stubTurnFor({ message: fixtures.clarify[locale].message, locale });
    expect(clarify!).toContain('"type":"clarify"');
    // Pressing the two answers sends the clarify round back: answered with the plan.
    const answered = stubTurnFor({
      message: fixtures.clarify[locale].message,
      locale,
      clarifications: [{ field: "nursery_time", value: "lt1m" }, { field: "general_state", value: "yes" }],
    });
    expect(answered!).toContain("event: token");
  }
  // Anything else is not the stub's: it goes on to the model guard.
  expect(stubTurnFor({ message: "tiene los labios morados y le cuesta mucho respirar", locale: "es" })).toBeNull();
  expect(stubTurnFor({ card_action: { intent: "confirm" } })).toBeNull();
});

test("the report is one HTML page: problems first, everything escaped, shots linked relative", () => {
  const html = renderReport({
    baseURL: "https://adelia.godi.ai",
    startedAt: "2026-11-10T03:04:05.000Z",
    runDir: "/tmp/u1",
    checks: [{ id: "10", title: "10 Primera pantalla", ok: false, detail: "<b>x</b>", durationMs: 1000 }],
    issues: [{ kind: "control-covered", where: "landing.360.es.light", detail: "banner <covers> «Preguntar»" }],
    metrics: [{ section: "perf", key: "landing", values: { lcpMs: 2100, typeMs: 900, jsKB: 310 } }],
    journeys: [{ name: "Recorrido completo", steps: [{ name: "portada", taps: 1, ms: 1200, ok: true }] }],
    shots: ["/tmp/u1/10-panel-390-es-light.png"],
  });
  expect(html.startsWith("<!doctype html>")).toBe(true);
  expect(html).toContain('lang="es"');
  expect(html).not.toContain("<b>x</b>");
  expect(html).toContain("&lt;covers&gt;");
  expect(html.indexOf("Problemas")).toBeLessThan(html.indexOf("Recorridos"));
  expect(html).toContain('src="10-panel-390-es-light.png"');
  expect(html).toContain("2100");
  expect(html).not.toMatch(/\u2014/);
});

test("the report groups a kind of problem once, its cases under it, and adds what was seen by eye", () => {
  const html = renderReport({
    baseURL: "x", startedAt: "t", runDir: "/tmp/u1", checks: [], metrics: [], journeys: [], shots: [],
    issues: [
      { kind: "small-target", where: "a", detail: "«Chat» 28x28" },
      { kind: "small-target", where: "b", detail: "«GitHub» 37x48" },
      { kind: "clarify-thumb", where: "c", detail: "«O escríbemelo» no se ve" },
    ],
    observations: ["«Nueva conversación» <baja> a otra fila a 360 px"],
  });
  expect(html.match(/Zonas táctiles de menos de 44 px/g)).toHaveLength(1);
  expect(html.indexOf("pulgar")).toBeLessThan(html.indexOf("Zonas táctiles"));
  expect(html).toContain("&lt;baja&gt;");
  expect(html.indexOf("&lt;baja&gt;")).toBeLessThan(html.indexOf("Recorridos"));
});
