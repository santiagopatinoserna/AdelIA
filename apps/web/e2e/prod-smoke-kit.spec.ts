import { expect, test } from "@playwright/test";
import { join } from "node:path";

import ciConfig from "../playwright.config";
import {
  ADMIN_READS,
  DEFAULT_BASE_URL,
  URGENT_QUESTIONS,
  adminFigures,
  boxesOverlap,
  checkId,
  foreignAges,
  isAnalyticsCollect,
  isModelPath,
  leakedFragments,
  monthsInGrowthMark,
  refuseModelTurn,
  smokeSettings,
  summarize,
} from "../e2e-prod/kit";

// The production smoke suite (e2e-prod/) runs against the live site, so the
// parts that decide what it may send and what it reports are pinned here,
// with no server: CI runs this file and never the suite itself. The rule
// behind most of it: a smoke run never makes the model answer (Santiago,
// 2026-11-08), so only the red-flag questions the guard answers in code may
// reach the agent (apps/api/tests/test_prod_smoke_questions.py pins that they
// are red flags).

const NOW = new Date(2026, 10, 8, 3, 4, 5);

test("defaults: the live site, Playwright's Chromium, shots under the home folder", () => {
  const s = smokeSettings({}, { home: "/home/hermes", now: NOW });
  expect(DEFAULT_BASE_URL).toBe("https://adelia.godi.ai");
  expect(s.baseURL).toBe("https://adelia.godi.ai");
  expect(s.channel).toBeUndefined();
  expect(s.runDir).toBe(
    join("/home/hermes", "dev/adelia-design/shots/prod-smoke", "2026-11-08_03-04-05"),
  );
});

test("the URL, the browser channel and the run folder come from the environment", () => {
  const s = smokeSettings(
    {
      PROD_SMOKE_URL: "http://localhost:3112/",
      PW_CHANNEL: "chrome",
      PROD_SMOKE_RUN_DIR: "/tmp/run-1",
    },
    { home: "/home/hermes", now: NOW },
  );
  expect(s.baseURL).toBe("http://localhost:3112");
  expect(s.channel).toBe("chrome");
  expect(s.runDir).toBe("/tmp/run-1");
});

test("CI's e2e config never picks up the production suite", () => {
  expect(ciConfig.testDir).toBe("./e2e");
});

test("only the two urgent questions may reach the agent, and nothing else that answers", () => {
  expect(URGENT_QUESTIONS).toEqual([
    "tiene los labios morados y le cuesta mucho respirar",
    "y ahora está muy decaída, no hay manera de despertarla",
  ]);
  for (const message of URGENT_QUESTIONS) {
    expect(refuseModelTurn({ message, locale: "es" })).toBeNull();
  }
  expect(refuseModelTurn({ message: "¿Es normal que regurgite?" })).toMatch(/not a red flag/);
  expect(refuseModelTurn({ message: URGENT_QUESTIONS[0] + " " })).toMatch(/not a red flag/);
  // A clarify answer or a card confirmation runs other nodes first.
  expect(
    refuseModelTurn({ message: URGENT_QUESTIONS[0], clarification: { field: "age", value: "0-3" } }),
  ).toMatch(/clarification/);
  expect(refuseModelTurn({ message: URGENT_QUESTIONS[0], card_action: { intent: "confirm" } }))
    .toMatch(/card_action/);
  expect(refuseModelTurn(null)).toMatch(/no JSON body/);
});

test("the answering endpoints are recognised on any host, and the rest are not", () => {
  for (const url of [
    "https://adelia.godi.ai/api/demo/ask",
    "https://adelia.godi.ai/api/demo/ask?locale=es",
    "https://adelia.godi.ai/api/chat",
    "https://adelia.godi.ai/api/chat/stream",
    "https://adelia.godi.ai/api/agent/turn",
    "https://adelia.godi.ai/api/backend/chat/sessions/1/messages",
    "https://adelia.godi.ai/api/backend/agent/turn",
    "http://localhost:3112/api/backend/agent/turn",
  ]) {
    expect(isModelPath(url), url).toBe(true);
  }
  for (const url of [
    "https://adelia.godi.ai/es",
    "https://adelia.godi.ai/api/version",
    "https://adelia.godi.ai/api/backend/agent/suggestions?locale=es",
    "https://adelia.godi.ai/api/backend/agent/thread",
    "https://adelia.godi.ai/api/demo/profile",
    "https://adelia.godi.ai/es/chat-guide",
  ]) {
    expect(isModelPath(url), url).toBe(false);
  }
});

test("Lucía's age is read from the height mark in the three languages", () => {
  expect(monthsInGrowthMark("Lucía · 5 meses")).toBe(5);
  expect(monthsInGrowthMark("LUCÍA · 1 MES")).toBe(1);
  expect(monthsInGrowthMark("Lucía · 7 months")).toBe(7);
  expect(monthsInGrowthMark("Lucía · 7 mois")).toBe(7);
  expect(monthsInGrowthMark("Lucía · 20 días")).toBe(0);
  expect(monthsInGrowthMark("Lucía")).toBeNull();
});

test("an example question may name the child's own age or none, never another", () => {
  expect(foreignAges("Regurgita después de cada toma, ¿hacia cuándo mejora?", 5)).toEqual([]);
  expect(foreignAges("¿Es normal que con 5 meses regurgite?", 5)).toEqual([]);
  // The production bug of 2026-11-06: Lucía, 5 months, was offered this.
  expect(foreignAges("¿Es normal que con 13 meses solo quiera leche materna?", 5)).toEqual([
    "13 meses",
  ]);
  expect(foreignAges("My 2-year-old only wants milk", 5)).toEqual(["2-year"]);
  expect(foreignAges("Mon bébé de 1 an refuse les légumes", 12)).toEqual([]);
  // Unknown age: any age named is suspect.
  expect(foreignAges("Con 5 meses, ¿es normal?", null)).toEqual(["5 meses"]);
});

test("check ids come from the title prefix", () => {
  expect(checkId("1.es Portada en es")).toBe("1.es");
  expect(checkId("5 /healthz y /api/version")).toBe("5");
  expect(checkId("Sin número")).toBe("Sin número");
});

test("the summary says ok only when every check that ran passed, and keeps the detail", () => {
  const meta = { baseURL: "https://adelia.godi.ai", runDir: "/tmp/r", startedAt: "t0" };
  const passed = summarize(meta, [
    { title: "1.es Portada", status: "passed", durationMs: 10, notes: ["buildId 1"], shots: ["a.png"] },
    { title: "6 Banner de cookies", status: "skipped", durationMs: 0, notes: [], shots: [] },
  ]);
  expect(passed.ok).toBe(true);
  expect(passed.checks[0]).toEqual({
    id: "1.es",
    title: "1.es Portada",
    ok: true,
    status: "passed",
    detail: "buildId 1",
    duration_ms: 10,
    shots: ["a.png"],
  });
  expect(passed.checks[1].ok).toBeNull();
  expect(passed.checks[1].detail).toBe("not run");

  const failed = summarize(meta, [
    { title: "2 Invitada", status: "failed", durationMs: 5, error: "\u001b[31mExpected Lucía\u001b[39m\nat x", notes: [], shots: [] },
    { title: "3 Conversación", status: "timedOut", durationMs: 5, notes: [], shots: [] },
  ]);
  expect(failed.ok).toBe(false);
  expect(failed.checks[0]).toMatchObject({ ok: false, detail: "Expected Lucía\nat x" });
  expect(failed.checks[1]).toMatchObject({ ok: false, detail: "timedOut" });
  expect(failed.base_url).toBe("https://adelia.godi.ai");
  expect(failed.run_dir).toBe("/tmp/r");
});

test("a guest the suite created and could not erase fails the run, whatever the checks say", () => {
  const meta = { baseURL: "https://adelia.godi.ai", runDir: "/tmp/r", startedAt: "t0" };
  const ok = [{ title: "5 Salud", status: "passed", durationMs: 1, notes: [], shots: [] }];
  const erased = { id: "6f1c", erased: true, detail: "erased in Settings" };
  const left = { id: "9a2b", erased: false, detail: "DELETE /users/me -> 500" };
  expect(summarize(meta, ok, [erased]).ok).toBe(true);
  const run = summarize(meta, ok, [erased, left]);
  expect(run.ok).toBe(false);
  expect(run.guests).toEqual([erased, left]);
});

// --- checks 6 and 7: the cookie banner and the admin page ---------------------

test("the banner overlaps a control only when their boxes really cross", () => {
  const banner = { x: 0, y: 700, width: 390, height: 144 };
  expect(boxesOverlap(banner, { x: 20, y: 650, width: 100, height: 52 })).toBe(true);
  expect(boxesOverlap(banner, { x: 20, y: 640, width: 100, height: 60 })).toBe(false);
  expect(boxesOverlap(banner, { x: 20, y: 844, width: 100, height: 40 })).toBe(false);
  expect(boxesOverlap(banner, { x: 0, y: 0, width: 390, height: 844 })).toBe(true);
});

test("a question leaks into an analytics batch raw, URL-encoded or in another case", () => {
  const question = "Prueba de humo: no enviar";
  const clean = JSON.stringify({ events: [{ type: "click", element: "landing-ask", path: "/es" }] });
  expect(leakedFragments([clean], [question])).toEqual([]);
  expect(leakedFragments([clean, `{"q":"${question}"}`], [question])).toEqual([question]);
  expect(leakedFragments([encodeURIComponent(question)], [question])).toEqual([question]);
  expect(leakedFragments([question.replace(/ /g, "+")], [question])).toEqual([question]);
  expect(leakedFragments([question.toUpperCase()], [question])).toEqual([question]);
});

test("only the analytics batch endpoint is a collect request", () => {
  expect(isAnalyticsCollect("https://adelia.godi.ai/api/analytics/collect")).toBe(true);
  expect(isAnalyticsCollect("http://localhost:3110/api/analytics/collect?x=1")).toBe(true);
  expect(isAnalyticsCollect("https://adelia.godi.ai/api/analytics/consent")).toBe(false);
  expect(isAnalyticsCollect("https://adelia.godi.ai/api/funnel/visit")).toBe(false);
});

test("the admin reads are the analytics summary, its access probe and the API usage", () => {
  expect(ADMIN_READS).toEqual([
    "/api/backend/analytics/access",
    "/api/backend/analytics/summary",
    "/api/backend/funnel/summary",
    "/api/backend/funnel/usage",
  ]);
});

test("an admin body is recognised by its figures, a refusal is not", () => {
  expect(adminFigures('{"detail":"Not Found"}')).toEqual([]);
  expect(adminFigures("")).toEqual([]);
  expect(adminFigures('{"days":30,"totals":{"visitors":3},"funnel":[]}')).toEqual(["totals", "funnel"]);
  expect(adminFigures('{"rows":[],"links":[]}')).toEqual(["rows", "links"]);
  expect(adminFigures('{"estimated_usd":1.2,"active_accounts":4}')).toEqual([
    "estimated_usd",
    "active_accounts",
  ]);
});

