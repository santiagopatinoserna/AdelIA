import { defineConfig } from "@playwright/test";
import { homedir } from "node:os";
import { join } from "node:path";

import { QA_HEADERS } from "../kit";
import { usabilitySettings } from "./kit";

// The usability battery (Santiago, 2026-11-10: "verifica la usabilidad, la
// fluidez"): first-screen budgets, tap targets, overlaps, the keyboard,
// reading order, axe, mobile performance and whole journeys, at 360, 390,
// 430 and a tablet, light and dark, es/en/fr. Not part of CI or of the smoke
// run. Like the smoke suite it never makes a model answer (README.md).
//
//   pnpm --filter @adelia/web usability:prod                      # https://adelia.godi.ai
//   PW_CHANNEL=chrome pnpm --filter @adelia/web usability:prod    # Santiago's Mac
//   PROD_SMOKE_URL=http://localhost:3118 pnpm --filter @adelia/web usability:prod

const settings = usabilitySettings(process.env, { home: homedir(), now: new Date() });
// Workers load this file again: they must write into the same run folder.
process.env.USABILITY_RUN_DIR = settings.runDir;

// Branded Chrome on macOS through the e2e suite's quiet launcher
// (scripts/redesign/chrome-quiet-stdio.sh says why).
const browser =
  settings.channel === "chrome" && process.platform === "darwin"
    ? { launchOptions: { executablePath: join(__dirname, "../../scripts/redesign/chrome-quiet-stdio.sh") } }
    : { channel: settings.channel };

export default defineConfig({
  testDir: ".",
  // One guest at a time on production, in file order: 00 opens the battery's
  // guest, 50 erases it, 60 is the whole journey with a guest of its own.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 300_000,
  expect: { timeout: 15_000 },
  outputDir: join(settings.runDir, "artifacts"),
  // A guest left behind by a crash is erased here, with the same checks as
  // the smoke suite's cleanup (only that id, only if the API says guest).
  globalTeardown: "./teardown.ts",
  use: {
    ...browser,
    baseURL: settings.baseURL,
    // Test traffic: served as usual, left out of every count (kit.QA_HEADERS).
    extraHTTPHeaders: { ...QA_HEADERS },
    viewport: { width: 390, height: 844 },
    locale: "es-ES",
    // The service worker would hide requests from the model guard.
    serviceWorkers: "block",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: [["line"], ["./report-reporter.ts"]],
});
