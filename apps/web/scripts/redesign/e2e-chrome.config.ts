import { defineConfig } from "@playwright/test";
import { join } from "node:path";

import base from "../../playwright.config";

// The whole e2e suite in the installed Google Chrome instead of Playwright's
// bundled Chromium: the redesign is verified in the browser a phone user's
// desktop twin actually runs (docs/design/REDISENO.md).
//   pnpm exec playwright test -c scripts/redesign/e2e-chrome.config.ts
//
// On macOS Chrome is launched through chrome-quiet-stdio.sh (same binary, same
// flags, stdout and stderr on /dev/null): the helpers it leaves behind kept
// the workers from exiting, see that script. Elsewhere the channel as before.
export const realChromeUse =
  process.platform === "darwin"
    ? {
        launchOptions: {
          ...base.use?.launchOptions,
          executablePath: join(__dirname, "chrome-quiet-stdio.sh"),
        },
      }
    : { channel: "chrome" };

export default defineConfig({
  ...base,
  testDir: "../../e2e",
  use: { ...base.use, ...realChromeUse },
});
