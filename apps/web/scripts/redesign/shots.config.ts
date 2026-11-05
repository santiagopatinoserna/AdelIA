import { defineConfig } from "@playwright/test";

import { realChromeUse } from "./e2e-chrome.config";

// Before/after captures of the mother-first redesign (docs/design/AUDITORIA_UX.md).
// Not part of `pnpm e2e`: it writes ~250 PNGs and a metrics file, and it runs
// in the real Chrome install on purpose (the product is judged on what a phone
// browser draws, not on Playwright's bundled Chromium).
//
//   SHOTS_PHASE=before pnpm exec playwright test -c scripts/redesign/shots.config.ts
//
// Needs the API on :8000 and the built web app on :3001, like the e2e suite,
// and the same AUTH_SECRET in the environment as the running web app.
export default defineConfig({
  testDir: ".",
  testMatch: /.*\.shots\.ts/,
  timeout: 150_000,
  workers: 3,
  fullyParallel: true,
  retries: 0,
  use: {
    // The installed Chrome, launched so its helpers cannot keep a worker alive
    // (chrome-quiet-stdio.sh), unless SHOTS_CHANNEL names another browser.
    ...(process.env.SHOTS_CHANNEL ? { channel: process.env.SHOTS_CHANNEL } : realChromeUse),
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3001",
  },
  reporter: [["list"]],
});
