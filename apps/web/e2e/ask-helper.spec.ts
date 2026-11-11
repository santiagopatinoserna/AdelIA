import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import chromeConfig from "../scripts/redesign/e2e-chrome.config";
import config from "../playwright.config";
import { ask } from "./utils/ask";

// The e2e suite kept failing now and then on the same race, each time in a
// different spec (usability-findings in #72, panel-clean's red flag after it):
// the test typed or tapped before React hydrated the field, or public/sw.js,
// which registers on hydration, took the page and carried the mocked turn past
// page.route to the real API ("Ahora no puedo responderte"). The fix is once,
// for the whole suite: every spec asks through utils/ask.ts, which waits for
// hydration, and no context gets a service worker unless it is the spec about
// the service worker. This file keeps both true.

const E2E = __dirname;
const SPECS = readdirSync(E2E).filter((f) => f.endsWith(".spec.ts"));
// The one spec about public/sw.js itself: it needs the worker.
const SERVICE_WORKER_SPECS = ["pwa-sw.spec.ts"];
// Types before hydration on purpose: that is what it tests.
const BEFORE_HYDRATION_SPECS = ["prehydration-ask.spec.ts"];

// Comments out, so a sentence that quotes the old pattern is not a statement.
const code = (file: string) =>
  readFileSync(join(E2E, file), "utf8").split("\n")
    .filter((line) => !line.trim().startsWith("//")).join("\n");

test("the suite blocks the service worker, in Playwright's Chromium and in real Chrome", () => {
  expect(config.use?.serviceWorkers).toBe("block");
  expect(chromeConfig.use?.serviceWorkers).toBe("block");
});

test("only the service worker's own spec lets it in", () => {
  const allowing = SPECS.filter((f) => /serviceWorkers:\s*"allow"/.test(code(f)));
  expect(allowing).toEqual(SERVICE_WORKER_SPECS);
});

test("no spec sends a question with a bare fill and Enter or a tap on send", () => {
  // A fill whose very next statement presses Enter, or taps the landing's
  // "Preguntar" or the panel's send button, is the racy pattern: ask() does
  // the same two steps once the field is hydrated.
  const SEND_TAP = /\.click\(/;
  const SEND_TARGET = /Preguntar|askCta|agent\.send|demo-ask|button\[type="submit"\]/;
  const offenders: string[] = [];
  for (const file of SPECS.filter((f) => !BEFORE_HYDRATION_SPECS.includes(f))) {
    const statements = code(file).split(";").map((s) => s.trim());
    statements.forEach((s, i) => {
      const next = statements[i + 1] ?? "";
      if (!/\.fill\(/.test(s)) return;
      if (/\.press\(\s*"Enter"\s*\)/.test(next) || (SEND_TAP.test(next) && SEND_TARGET.test(next))) {
        offenders.push(`${file}: ${s.replace(/\s+/g, " ").slice(0, 90)}`);
      }
    });
  }
  expect(offenders).toEqual([]);
});

test("a context a spec opens with its own options gets no service worker either", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true });
  const page = await context.newPage();
  await page.goto("/es");
  const field = page.locator("#demo-question");
  await expect.poll(() => field.evaluate((el) => Object.keys(el).some((k) => k.startsWith("__reactProps$"))),
    { timeout: 30_000 }).toBe(true);
  // public/sw.js registers on hydration and controls the page within some
  // 50 ms: give it far more than that.
  await page.waitForTimeout(2_000);
  expect(await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)).toBe(0);
  expect(await page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(false);
  await context.close();
});

// Every script chunk waits until the test opens the gate (as in
// prehydration-ask.spec.ts): the field is on screen and takes text, and React
// has not hydrated it yet.
async function holdScripts(page: Page) {
  let open!: () => void;
  const gate = new Promise<void>((resolve) => { open = resolve; });
  await page.route("**/_next/static/chunks/**", async (route) => {
    await gate;
    await route.continue().catch(() => {});
  });
  return open;
}

test("ask() types only once React has hydrated the field, then sends once", async ({ page }) => {
  const question = "¿Es normal que regurgite después de cada toma?";
  const sent: string[] = [];
  // No guest space (the API brakes guest creation per address): the landing
  // answers through its keyless fallback, the same field and the same send.
  await page.route("**/api/auth/callback/guest**", (route) => route.abort());
  await page.route("**/api/demo/ask", (route) => {
    sent.push(String(route.request().postDataJSON().question ?? ""));
    return route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ kind: "answer", intent: "question", answer: "Respuesta simulada.",
        evidence_citations: [], disclaimer: "Aviso." }),
    });
  });
  const open = await holdScripts(page);
  await page.goto("/es", { waitUntil: "commit" });
  const field = page.locator("#demo-question");
  await expect(field).toBeVisible();

  const asking = ask(field, question);
  await page.waitForTimeout(1_000);
  expect(await field.inputValue(), "ask() typed into a field React had not hydrated").toBe("");
  open();
  await asking;
  await expect.poll(() => sent, { timeout: 30_000 }).toEqual([question]);
  await page.waitForTimeout(1_000);
  expect(sent).toEqual([question]);
});
