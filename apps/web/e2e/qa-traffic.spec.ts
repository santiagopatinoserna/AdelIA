import { type APIRequestContext, expect, test } from "@playwright/test";
import { Pool } from "pg";

import { QA_HEADER, qaHeaders } from "../lib/qa-traffic";

// Test traffic stays out of the numbers (2026-11-08). A request carrying
// X-AdelIA-QA: 1 is served like any other and is left out of the anonymous
// funnel, the analytics, the /r/ clicks and the usage counter
// (apps/api/adelia/qa_traffic.py). The browser reaches the API through this
// server's own routes, so each of them has to pass the header on; these cases
// hold every one of those doors to it against the running stack.

const QA = { [QA_HEADER]: "1" };
// A person's phone: the /r/ route never counts a link preview or a headless
// browser, so without it a click would go uncounted whatever the header said.
const PHONE_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 " +
  "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1";

function pool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

async function query<T = Record<string, unknown>>(sql: string, params: unknown[] = []): Promise<T[]> {
  const db = pool();
  try {
    return (await db.query(sql, params)).rows as T[];
  } finally {
    await db.end();
  }
}

/** Today's value of one funnel counter, in UTC like services/funnel. */
async function counter(event: string): Promise<number> {
  const rows = await query<{ count: number }>(
    `SELECT count FROM funnel_counters
      WHERE day = (now() AT TIME ZONE 'UTC')::date AND event = $1`,
    [event],
  );
  return Number(rows[0]?.count ?? 0);
}

const TRIES = 5;

test.describe("pure", () => {
  test("only the value 1 is passed on, under the API's own name", () => {
    expect(QA_HEADER).toBe("X-AdelIA-QA");
    expect(qaHeaders(new Headers({ "x-adelia-qa": "1" }))).toEqual({ "X-AdelIA-QA": "1" });
    expect(qaHeaders(new Headers({ "X-AdelIA-QA": " 1 " }))).toEqual({ "X-AdelIA-QA": "1" });
    for (const value of ["0", "true", "yes", ""]) {
      expect(qaHeaders(new Headers({ "x-adelia-qa": value })), value).toEqual({});
    }
    expect(qaHeaders(new Headers())).toEqual({});
    expect(qaHeaders(undefined)).toEqual({});
  });
});

test.describe("against the stack", () => {
  test.use({ userAgent: PHONE_UA });

  // Other runs may count real visits meanwhile; they only add. Five test
  // requests that were counted would show as five more, whatever else happens.
  test("a test visit and a test start are not counted", async ({ request }) => {
    for (const event of ["visit", "start"]) {
      const before = await counter(event);
      for (let i = 0; i < TRIES; i++) {
        const res = await request.post(`/api/funnel/${event}`, { headers: QA });
        expect(res.status()).toBe(204);
      }
      await new Promise((r) => setTimeout(r, 300));
      expect((await counter(event)) - before, event).toBeLessThan(TRIES);
    }
  });

  test("a test click on a short link goes to the same place and is not counted", async ({ request }) => {
    const before = await counter("link_g07");
    for (let i = 0; i < TRIES; i++) {
      const res = await request.get("/r/g07", { headers: QA, maxRedirects: 0 });
      expect(res.status()).toBe(302);
      expect(res.headers()["location"]).toContain("utm_content=g07");
    }
    await new Promise((r) => setTimeout(r, 300));
    expect((await counter("link_g07")) - before).toBeLessThan(TRIES);
  });

  test("a test consent and a test batch are not stored", async ({ request }) => {
    const accepted = crypto.randomUUID();
    const tested = crypto.randomUUID();
    const answer = { choice: "accepted", version: "2026-11-08", source: "banner" };
    expect((await request.post("/api/analytics/consent", { data: { consent_id: accepted, ...answer } })).status()).toBe(204);
    expect(
      (await request.post("/api/analytics/consent", { headers: QA, data: { consent_id: tested, ...answer } })).status(),
    ).toBe(204);
    const session = crypto.randomUUID();
    const batch = {
      consent_id: accepted,
      visitor_id: crypto.randomUUID(),
      session_id: session,
      context: { locale: "es", landing_path: "/es" },
      events: [{ ts: Date.now(), type: "pageview", path: "/es" }],
    };
    const res = await request.post("/api/analytics/collect", {
      headers: { ...QA, "content-type": "text/plain" },
      data: JSON.stringify(batch),
    });
    expect(res.status()).toBe(204);

    try {
      const consents = await query<{ consent_id: string }>(
        "SELECT consent_id::text FROM analytics_consents WHERE consent_id = ANY($1::uuid[])",
        [[accepted, tested]],
      );
      expect(consents.map((r) => r.consent_id)).toEqual([accepted]);
      expect(await query("SELECT 1 FROM analytics_sessions WHERE session_id = $1", [session])).toEqual([]);
    } finally {
      await query("DELETE FROM analytics_consents WHERE consent_id = ANY($1::uuid[])", [[accepted, tested]]);
    }
  });

  test("a guest opened by test traffic is a guest the funnel leaves out", async ({ playwright, baseURL }) => {
    const tester: APIRequestContext = await playwright.request.newContext({
      baseURL,
      userAgent: PHONE_UA,
      extraHTTPHeaders: QA,
    });
    let id: string | null = null;
    try {
      const { csrfToken } = (await (await tester.get("/api/auth/csrf")).json()) as { csrfToken: string };
      const signIn = await tester.post("/api/auth/callback/guest", {
        form: { csrfToken, locale: "es", json: "true" },
        maxRedirects: 0,
      });
      expect(signIn.status()).toBeLessThan(400);
      const session = (await (await tester.get("/api/auth/session")).json()) as { user?: { id?: string } };
      id = session.user?.id ?? null;
      expect(id).toBeTruthy();

      const [row] = await query<{ email: string; is_guest: boolean }>(
        "SELECT email, is_guest FROM users WHERE id = $1",
        [id],
      );
      expect(row.is_guest).toBe(true);
      expect(row.email).toMatch(/^qa-invitado-.+@guest\.adelia\.invalid$/);

      // And she leaves the usual way, through the backend proxy.
      expect((await tester.delete("/api/backend/users/me")).status()).toBe(204);
      expect(await query("SELECT 1 FROM users WHERE id = $1", [id])).toEqual([]);
      id = null;
    } finally {
      if (id) await query("DELETE FROM users WHERE id = $1 AND is_guest", [id]);
      await tester.dispose();
    }
  });
});
