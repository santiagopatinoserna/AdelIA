import { defineConfig } from "@playwright/test";
import { homedir } from "node:os";
import { join } from "node:path";

import { QA_HEADERS, smokeSettings } from "./kit";

// Production smoke suite: what Hermes runs after a deploy instead of writing
// Playwright scripts on the fly (Santiago, 2026-11-08). Not part of CI: the CI
// config only reads ./e2e. Never makes a model answer (see README.md).
//
//   pnpm --filter @adelia/web smoke:prod                       # https://adelia.godi.ai
//   PW_CHANNEL=chrome pnpm --filter @adelia/web smoke:prod     # Santiago's Mac
//   PROD_SMOKE_URL=http://localhost:3112 pnpm --filter @adelia/web smoke:prod

const settings = smokeSettings(process.env, { home: homedir(), now: new Date() });
// Workers load this file again: they must write into the same run folder.
process.env.PROD_SMOKE_RUN_DIR = settings.runDir;

// Branded Chrome on macOS through the same quiet launcher as the e2e suite:
// its leftover helpers otherwise keep the worker from exiting
// (scripts/redesign/chrome-quiet-stdio.sh says why).
const browser =
  settings.channel === "chrome" && process.platform === "darwin"
    ? {
        launchOptions: {
          executablePath: join(__dirname, "../scripts/redesign/chrome-quiet-stdio.sh"),
        },
      }
    : { channel: settings.channel };

export default defineConfig({
  testDir: ".",
  // One guest, one conversation, in order: never two at once on production.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: join(settings.runDir, "artifacts"),
  use: {
    ...browser,
    baseURL: settings.baseURL,
    // Test traffic: served as usual, left out of every count (kit.QA_HEADERS).
    extraHTTPHeaders: { ...QA_HEADERS },
    viewport: { width: 390, height: 844 },
    locale: "es-ES",
    // The service worker would hide requests from the model guard (browser.ts).
    serviceWorkers: "block",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: [["line"], ["./summary-reporter.ts"]],
});
