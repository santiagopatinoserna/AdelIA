import { defineConfig } from "@playwright/test";

import base from "../../playwright.config";

// The whole e2e suite in the installed Google Chrome instead of Playwright's
// bundled Chromium: the redesign is verified in the browser a phone user's
// desktop twin actually runs (docs/design/REDISENO.md).
//   pnpm exec playwright test -c scripts/redesign/e2e-chrome.config.ts
export default defineConfig({
  ...base,
  testDir: "../../e2e",
  use: { ...base.use, channel: "chrome" },
});
