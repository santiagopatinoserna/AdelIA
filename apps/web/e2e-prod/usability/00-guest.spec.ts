import { expect, test } from "@playwright/test";
import { copyFileSync } from "node:fs";
import { join } from "node:path";

import { armModelGuard, sessionUserId } from "../browser";
import { saveGuest } from "../guests";
import { GUEST_STATE, RUN_DIR, note } from "./page";

// The battery's guest: opened the way a mother opens it (the landing's record
// button), with Lucía and no conversation yet, so 10 measures the panel of a
// first visit. 20 starts her thread, 50 erases her. Her session is saved for
// the checks in between, and under her id for the teardown.

test("00 Invitada de la batería", async ({ page, context }) => {
  const guard = await armModelGuard(context);
  await page.goto("/es");
  await page.getByTestId("landing-record").click();
  await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar/, { timeout: 30_000 });
  const id = await sessionUserId(page);
  expect(id, "a guest session after the record button").toBeTruthy();
  saveGuest(RUN_DIR, { id: id!, erased: false, detail: "battery guest, opened by 00" });
  await context.storageState({ path: join(RUN_DIR, `guest-${id}.json`) });
  copyFileSync(join(RUN_DIR, `guest-${id}.json`), GUEST_STATE());
  await page.goto("/es/dashboard");
  await expect(page.getByTestId("today-card")).toContainText("Lucía");
  expect(guard.modelRequests).toEqual([]);
  note(`guest ${id!.slice(0, 8)}`);
});
