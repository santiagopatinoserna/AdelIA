import { type BrowserContext, type Page, expect, test } from "@playwright/test";

import { type ModelGuard, armModelGuard, eraseGuest, note, pageErrors, sessionUserId, shot } from "./browser";
import { saveGuest } from "./guests";
import { ADMIN_READS, adminFigures } from "./kit";

// Check 7: the analytics admin page and the API usage are for the admins
// only (auth.is_admin: ADMIN_EMAILS plus OWNER_EMAIL). The suite has no admin
// credentials and must not get any, so this is what a visitor and a guest
// get: no page, and no figure from any admin read, only a refusal.
//
// The guest comes from check 2's flow (the landing's record button, which
// asks no model) and is erased at the end by the same guarded DELETE as
// check 2's cleanup; afterAll erases her if anything failed first. This file
// runs after 02-guest.spec.ts has erased its own, with one worker: there is
// never more than one guest open at a time.

const RUN_DIR = process.env.PROD_SMOKE_RUN_DIR!;

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
let guard: ModelGuard;
let errors: string[];
const guest: { id: string | null; erased: boolean } = { id: null, erased: false };

/** Each admin read as "path -> status", and the figures a body let out. */
async function adminReads(p: Page): Promise<{ statuses: string[]; leaks: string[] }> {
  const statuses: string[] = [];
  const leaks: string[] = [];
  for (const path of ADMIN_READS) {
    const res = await p.request.get(path, { maxRedirects: 0 });
    statuses.push(`${path} -> ${res.status()}`);
    const figures = adminFigures(await res.text().catch(() => ""));
    if (res.ok() || figures.length > 0) leaks.push(`${path} -> ${res.status()} ${figures.join(",")}`);
  }
  return { statuses, leaks };
}

test.beforeAll(async ({ browser }, testInfo) => {
  const use = testInfo.project.use;
  context = await browser.newContext({
    baseURL: use.baseURL,
    viewport: use.viewport,
    locale: use.locale,
    serviceWorkers: use.serviceWorkers,
    extraHTTPHeaders: use.extraHTTPHeaders,
  });
  guard = await armModelGuard(context);
  page = await context.newPage();
  errors = pageErrors(page);
});

test.afterAll(async () => {
  try {
    const id = guest.id ?? (await sessionUserId(page).catch(() => null));
    if (id && !guest.erased) {
      const outcome = await eraseGuest(page, id).catch((e: Error) => ({
        erased: false,
        detail: `cleanup failed: ${e.message}`,
      }));
      saveGuest(RUN_DIR, { id, ...outcome });
    }
  } finally {
    await context.close();
  }
});

test("7.visitante Administración: una visita sin sesión no ve nada", async () => {
  const res = await page.goto("/es/dashboard/admin");
  // The panel sends a visitor to sign in before the page is even asked.
  await expect(page).toHaveURL(/\/es\/signin/);
  expect(res?.status(), "after the redirect").toBe(200);
  await expect(page.getByTestId("admin-analytics")).toHaveCount(0);

  const { statuses, leaks } = await adminReads(page);
  expect(leaks, "admin reads that answered a visitor").toEqual([]);
  note(`visitor: /es/dashboard/admin -> sign-in; ${statuses.join("; ")}`);
});

test("7.invitada Administración: una invitada no la abre ni lee el uso de la API", async () => {
  await page.goto("/es");
  await page.getByTestId("landing-record").click();
  await expect(page).toHaveURL(/\/es\/dashboard\/consulta\/grabar/, { timeout: 30_000 });
  guest.id = await sessionUserId(page);
  expect(guest.id, "a guest session after the record button").toBeTruthy();
  saveGuest(RUN_DIR, { id: guest.id!, erased: false, detail: "created by check 7" });

  const res = await page.goto("/es/dashboard/admin");
  expect(res?.status(), "/es/dashboard/admin for a guest").toBe(404);
  await expect(page.getByTestId("admin-analytics")).toHaveCount(0);
  await shot(page, RUN_DIR, "07-admin-guest");

  // Settings carries no way in either.
  await page.goto("/es/dashboard/settings");
  await expect(page.getByTestId("settings-consent")).toBeVisible();
  await expect(page.getByTestId("settings-admin")).toHaveCount(0);

  const { statuses, leaks } = await adminReads(page);
  expect(leaks, "admin reads that answered a guest").toEqual([]);
  for (const line of statuses) expect(line, "a guest gets the 404 of a page that is not there").toMatch(/-> 404$/);

  // Erase her now, the same guarded way as check 2's cleanup.
  const outcome = await eraseGuest(page, guest.id!);
  guest.erased = outcome.erased;
  saveGuest(RUN_DIR, { id: guest.id!, ...outcome });
  expect(outcome.erased, outcome.detail).toBe(true);
  // The cookie may outlive her; the API no longer knows her.
  const after = await page.request.get("/api/backend/billing/status");
  expect(after.ok(), `billing status after erasure -> ${after.status()}`).toBe(false);

  expect(guard.modelRequests, "requests to an answering endpoint").toEqual([]);
  expect(errors, "uncaught page errors").toEqual([]);
  note(`guest ${guest.id!.slice(0, 8)}: admin page 404, ${statuses.join("; ")}; erased`);
});
