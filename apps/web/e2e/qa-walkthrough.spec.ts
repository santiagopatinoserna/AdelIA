/**
 * QA walkthrough — NOT part of the regression suite.
 *
 * Drives the real local stack (web :3001 + api :8000 + PG + MinIO + real
 * Mistral key) screen by screen, saving a screenshot per screen and a JSON
 * report of console errors / failed requests, then exercises the consulta
 * recording flow end-to-end with the two-voice fixture piped into Chromium's
 * fake microphone — real upload, real Voxtral transcription, no mocks.
 *
 * Run:  pnpm exec playwright test e2e/qa-walkthrough.spec.ts
 * Env:  QA_SHOTS_DIR (defaults to ./qa-shots)
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";

const SHOTS = process.env.QA_SHOTS_DIR ?? "qa-shots";
const FIXTURE_WAV = resolve(__dirname, "../../api/tests/fixtures/consulta-dos-voces.wav");

// Manual QA tool, not regression: it needs the full local stack with a real
// Mistral key and burns real transcription calls. CI must never run it.
test.skip(
  !process.env.QA_WALKTHROUGH,
  "QA tool — run with QA_WALKTHROUGH=1 against a full local stack",
);

test.use({
  launchOptions: {
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${FIXTURE_WAV}%noloop`,
    ],
  },
});

type PageIssues = {
  url: string;
  consoleErrors: string[];
  pageErrors: string[];
  failedRequests: string[];
};

function watch(page: Page, issues: PageIssues[]) {
  let current: PageIssues = { url: "", consoleErrors: [], pageErrors: [], failedRequests: [] };
  const fresh = (url: string) => {
    current = { url, consoleErrors: [], pageErrors: [], failedRequests: [] };
    issues.push(current);
  };
  page.on("console", (msg) => {
    if (msg.type() === "error") current.consoleErrors.push(msg.text().slice(0, 300));
  });
  page.on("pageerror", (err) => current.pageErrors.push(String(err).slice(0, 300)));
  page.on("response", (res) => {
    if (res.status() >= 400)
      current.failedRequests.push(`${res.status()} ${res.request().method()} ${res.url()}`);
  });
  return fresh;
}

async function shoot(page: Page, name: string) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
}

const PUBLIC_SCREENS: Array<[string, string]> = [
  ["/es", "public-landing"],
  ["/es/profesionales", "public-profesionales"],
  ["/es/privacidad", "public-privacidad"],
  ["/es/terminos", "public-terminos"],
];

const DASH_SCREENS: Array<[string, string]> = [
  ["/es/dashboard", "dash-agent-home"],
  ["/es/dashboard/overview", "dash-overview"],
  ["/es/dashboard/upload", "dash-upload"],
  ["/es/dashboard/chat", "dash-chat"],
  ["/es/dashboard/consulta", "dash-consulta"],
  ["/es/dashboard/consulta/grabar", "dash-grabar"],
  // /dashboard/documents has no list page by design (detail-only route);
  // overview is where documents are listed.
  ["/es/dashboard/overview", "dash-overview-docs"],
  ["/es/dashboard/briefings", "dash-briefings"],
  ["/es/dashboard/settings", "dash-settings"],
];

test("walkthrough desktop", async ({ page, context }) => {
  test.setTimeout(240_000);
  mkdirSync(SHOTS, { recursive: true });
  const issues: PageIssues[] = [];
  const fresh = watch(page, issues);

  for (const [url, name] of PUBLIC_SCREENS) {
    fresh(url);
    await page.goto(url);
    await shoot(page, `desktop-${name}`);
  }

  const { cookie } = await seedUserAndSessionCookie(`qa-walk-${Date.now()}@adelia.test`);
  await context.addCookies([cookie]);

  for (const [url, name] of DASH_SCREENS) {
    fresh(url);
    await page.goto(url);
    await shoot(page, `desktop-${name}`);
  }

  writeFileSync(join(SHOTS, "issues-desktop.json"), JSON.stringify(issues, null, 2));
});

test("walkthrough mobile", async ({ browser }) => {
  test.setTimeout(240_000);
  mkdirSync(SHOTS, { recursive: true });
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 3,
  });
  const page = await context.newPage();
  const issues: PageIssues[] = [];
  const fresh = watch(page, issues);

  const { cookie } = await seedUserAndSessionCookie(`qa-mob-${Date.now()}@adelia.test`);
  await context.addCookies([cookie]);

  const screens: Array<[string, string]> = [
    ["/es", "public-landing"],
    ["/es/privacidad", "public-privacidad"],
    ...DASH_SCREENS,
  ];
  for (const [url, name] of screens) {
    fresh(url);
    await page.goto(url);
    await shoot(page, `mobile-${name}`);
  }

  writeFileSync(join(SHOTS, "issues-mobile.json"), JSON.stringify(issues, null, 2));
  await context.close();
});

test("real recording end to end (no mocks, real Voxtral)", async ({ page, context }) => {
  test.setTimeout(300_000);
  mkdirSync(SHOTS, { recursive: true });

  const { cookie } = await seedUserAndSessionCookie(`qa-rec-${Date.now()}@adelia.test`);
  await context.addCookies([cookie]);

  await page.goto("/es/dashboard/consulta/grabar");
  await page.getByRole("checkbox").check();
  await shoot(page, "rec-1-gate-checked");

  await page.getByRole("button", { name: "Grabar" }).click();
  await expect(page.getByRole("status")).toContainText("Grabando", { timeout: 15_000 });
  await shoot(page, "rec-2-recording");

  // The fixture is ~13s + trailing silence; capture enough of it.
  await page.waitForTimeout(16_000);
  await page.getByRole("button", { name: "Terminar y guardar" }).click();

  // Real upload + real Voxtral transcription + extraction pipeline.
  await expect(page.getByText("Consulta guardada", { exact: false })).toBeVisible({
    timeout: 180_000,
  });
  await shoot(page, "rec-3-done");

  await page.getByRole("link", { name: "Ver la transcripción" }).click();
  await page.waitForLoadState("networkidle").catch(() => {});
  await shoot(page, "rec-4-document");

  const body = await page.textContent("body");
  writeFileSync(join(SHOTS, "rec-transcript-page.txt"), body ?? "");
  expect(body).toContain("Hablante");
});
