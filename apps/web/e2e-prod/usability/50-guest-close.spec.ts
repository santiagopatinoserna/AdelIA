import { expect, test } from "@playwright/test";
import { existsSync, readFileSync, rmSync } from "node:fs";

import { eraseGuest } from "../browser";
import { saveGuest } from "../guests";
import { GUEST_STATE, RUN_DIR, note } from "./page";

// The battery's guest goes before the journey opens its own: never two
// guests at once on production. Same guarded erasure as the smoke suite.

test("50 Borrar la invitada de la batería", async ({ browser, baseURL }) => {
  test.skip(!existsSync(GUEST_STATE()), "no battery guest");
  const state = JSON.parse(readFileSync(GUEST_STATE(), "utf8"));
  const context = await browser.newContext({ baseURL, storageState: state });
  try {
    const page = await context.newPage();
    const res = await page.request.get("/api/auth/session");
    const id = ((await res.json().catch(() => null)) as { user?: { id?: string } } | null)?.user?.id;
    expect(id, "the battery guest's session").toBeTruthy();
    const outcome = await eraseGuest(page, id!);
    saveGuest(RUN_DIR, { id: id!, ...outcome });
    expect(outcome.erased, outcome.detail).toBe(true);
    rmSync(GUEST_STATE());
    note(`battery guest ${id!.slice(0, 8)} erased`);
  } finally {
    await context.close();
  }
});
