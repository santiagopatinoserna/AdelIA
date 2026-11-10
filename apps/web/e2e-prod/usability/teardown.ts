import { chromium } from "@playwright/test";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { eraseGuest } from "../browser";
import { readGuests, saveGuest } from "../guests";
import { QA_HEADERS } from "../kit";
import { usabilitySettings } from "./kit";

// Last line of defence: a guest the run opened and did not erase (a crash, a
// timeout before 50 or the journey got there) is erased with its own saved
// session, and only if that session is still that id and the API calls it a
// guest (browser.eraseGuest). Never anything else.
export default async function teardown() {
  const { baseURL, runDir, channel } = usabilitySettings(process.env, { home: homedir(), now: new Date() });
  const left = readGuests(runDir).filter((g) => !g.erased);
  if (left.length === 0) return;
  const browser = await chromium.launch({ channel });
  try {
    for (const g of left) {
      const state = join(runDir, `guest-${g.id}.json`);
      if (!existsSync(state)) continue;
      const context = await browser.newContext({ baseURL, storageState: state, extraHTTPHeaders: { ...QA_HEADERS } });
      const page = await context.newPage();
      const outcome = await eraseGuest(page, g.id).catch((e: Error) => ({ erased: false, detail: `teardown: ${e.message}` }));
      saveGuest(runDir, { id: g.id, ...outcome, detail: `teardown: ${outcome.detail}` });
      await context.close();
    }
  } finally {
    await browser.close();
  }
}
