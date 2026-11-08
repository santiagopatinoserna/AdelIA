import { type BrowserContext, type Page, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { isModelPath, refuseModelTurn } from "./kit";

// The browser half of the suite: the model guard, screenshots, notes for the
// summary, and the guest's identity and emergency erasure.

export type ModelGuard = {
  /** Every request to an answering path, any method, as "METHOD /path". */
  modelRequests: string[];
  /** What the guard stopped before it left the browser. */
  violations: string[];
  /** Bodies of the agent turns it let through (red flags only). */
  turns: Record<string, unknown>[];
};

/**
 * No smoke run makes a model answer. Every POST to an answering path is
 * aborted in the browser unless it is an agent turn carrying one of the red
 * flags the graph's guard answers in code (kit.refuseModelTurn). GETs pass:
 * reading a stored thread or the suggestions costs nothing.
 */
export async function armModelGuard(context: BrowserContext): Promise<ModelGuard> {
  const guard: ModelGuard = { modelRequests: [], violations: [], turns: [] };
  context.on("request", (req) => {
    if (isModelPath(req.url())) guard.modelRequests.push(`${req.method()} ${new URL(req.url()).pathname}`);
  });
  await context.route(
    (url) => isModelPath(url.href),
    async (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      if (req.method() === "GET" || req.method() === "HEAD") return route.continue();
      if (path === "/api/backend/agent/turn") {
        let body: unknown = null;
        try {
          body = req.postDataJSON();
        } catch {
          body = null;
        }
        const refusal = refuseModelTurn(body);
        if (refusal === null) {
          guard.turns.push(body as Record<string, unknown>);
          return route.continue();
        }
        guard.violations.push(`${req.method()} ${path}: ${refusal}`);
        return route.abort("blockedbyclient");
      }
      guard.violations.push(`${req.method()} ${path}`);
      return route.abort("blockedbyclient");
    },
  );
  return guard;
}

/** A line for this check's `detail` in the summary. */
export function note(text: string): void {
  test.info().annotations.push({ type: "note", description: text });
}

/** A 390x844 screenshot in the run folder, listed under this check. */
export async function shot(page: Page, runDir: string, name: string): Promise<void> {
  mkdirSync(runDir, { recursive: true });
  const path = join(runDir, `${name}.png`);
  await page.screenshot({ path });
  test.info().attachments.push({ name, path, contentType: "image/png" });
}

/** Uncaught errors of the page, collected from now on. */
export function pageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

/** The signed-in user id of this browser context, or null. */
export async function sessionUserId(page: Page): Promise<string | null> {
  const res = await page.request.get("/api/auth/session");
  if (!res.ok()) return null;
  const body = (await res.json().catch(() => null)) as { user?: { id?: string } } | null;
  return body?.user?.id ?? null;
}

/**
 * Erase the guest this context opened when the Settings path did not. Only if
 * the session is still that same id AND the API says it is a guest: this
 * never deletes anything else, whatever state the page was left in.
 */
export async function eraseGuest(page: Page, id: string): Promise<{ erased: boolean; detail: string }> {
  const current = await sessionUserId(page);
  if (current === null) return { erased: false, detail: "no session left to erase it with" };
  if (current !== id) return { erased: false, detail: `session is ${current}, not the guest: left alone` };
  const status = await page.request.get("/api/backend/billing/status");
  const billing = (await status.json().catch(() => null)) as { is_guest?: boolean } | null;
  if (!billing?.is_guest) return { erased: false, detail: "the API does not call it a guest: left alone" };
  const res = await page.request.delete("/api/backend/users/me");
  return res.status() === 204
    ? { erased: true, detail: "erased by the cleanup (DELETE /users/me)" }
    : { erased: false, detail: `DELETE /users/me -> ${res.status()}` };
}
