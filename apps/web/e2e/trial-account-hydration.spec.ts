import { expect, test, type Page } from "@playwright/test";
import { Pool } from "pg";

import { behindCloudflareEmailObfuscation } from "./utils/cloudflare-email";
import { isoMonthsAgo, seedProfile } from "./utils/seed";
import { seedUserAndSessionCookie } from "./utils/session";

// React #418 on every visit to /dashboard/settings in production (build
// 20261106005133), with a brand-new account in its card-free trial, while
// every other panel page and every local run were clean. The cause was not
// the trial date: Cloudflare's Email Address Obfuscation rewrote the account
// email in the HTML ("Escribe <email> para confirmar:" in the danger zone),
// so the text React hydrated was not the text the server rendered. The fix is
// `Cache-Control: no-transform` on the pages that print an address
// (middleware.ts), which Cloudflare honours by leaving the HTML alone.
//
// This walks every /dashboard page, /billing and the public pages with the
// account that broke (trial, Nora of 4 months, a note, a PDF and a briefing)
// behind a simulated Cloudflare edge (utils/cloudflare-email.ts), with the
// server in UTC as in the container and the phone in Madrid, and fails on any
// hydration error.

// serviceWorkers "block": public/sw.js would take over navigations after the
// first page and fetch them where the simulated edge cannot see them.
test.use({
  timezoneId: "Europe/Madrid",
  viewport: { width: 390, height: 844 },
  serviceWorkers: "block",
});
// One locale per test, about 33 full page loads each.
test.setTimeout(240_000);

function pgPool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

const seededUserIds: string[] = [];

test.afterAll(async () => {
  if (seededUserIds.length === 0) return;
  const pool = pgPool();
  try {
    await pool.query(`DELETE FROM observations WHERE user_id = ANY($1::uuid[])`, [seededUserIds]);
    await pool.query(`DELETE FROM documents WHERE user_id = ANY($1::uuid[])`, [seededUserIds]);
    await pool.query(`DELETE FROM briefings WHERE user_id = ANY($1::uuid[])`, [seededUserIds]);
    await pool.query(`DELETE FROM users WHERE id = ANY($1::uuid[])`, [seededUserIds]);
  } finally {
    await pool.end();
  }
});

const HYDRATION = /hydrat|#418|#423|#425|did not match/i;

function watchHydration(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => {
    if (HYDRATION.test(e.message)) errors.push(`pageerror: ${e.message}`);
  });
  page.on("console", (msg) => {
    if (msg.type() === "error" && HYDRATION.test(msg.text())) errors.push(`console: ${msg.text()}`);
  });
  return errors;
}

/** The production account: card-free trial (status "none", trial from created_at). */
async function seedTrialAccount(tag: string) {
  const nonce = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const email = `e2e-trial-hyd-${tag}-${nonce}@example.com`;
  const { userId, cookie } = await seedUserAndSessionCookie(email);
  seededUserIds.push(userId);
  const profileId = await seedProfile(userId, {
    displayName: "Nora",
    dateOfBirth: isoMonthsAgo(4),
  });
  const pool = pgPool();
  try {
    await pool.query(
      `UPDATE users SET subscription_status = 'none', trial_end = NULL, stripe_customer_id = NULL,
                        created_at = now()
        WHERE id = $1`,
      [userId],
    );
    await pool.query(
      `INSERT INTO observations (user_id, profile_id, kind, value, unit, text, observed_at, source)
       VALUES ($1, $2, 'temperature', 37.6, '°C', 'ha tenido 37,6', now(), 'agent')`,
      [userId, profileId],
    );
    const b = await pool.query(
      `INSERT INTO briefings (user_id, profile_id, target_specialty, status, html_render,
                              created_at, completed_at, payload)
       VALUES ($1, $2, 'pediatrics', 'ready', '<h1>Informe de Nora</h1>', now(), now(), '{}'::jsonb)
       RETURNING id`,
      [userId, profileId],
    );
    // processed_at set: a row without it is requeued as a real pipeline by
    // the next API boot (CLAUDE.md).
    const d = await pool.query(
      `INSERT INTO documents (id, user_id, profile_id, source, mime_type, s3_key, raw_text,
                              created_at, processed_at)
       VALUES (gen_random_uuid(), $1, $2, 'manual', 'application/pdf', $3,
               'Documento de prueba e2e.', now(), now())
       RETURNING id`,
      [userId, profileId, `e2e/trial-hyd-${Date.now()}.pdf`],
    );
    return { cookie, briefingId: b.rows[0].id as string, documentId: d.rows[0].id as string };
  } finally {
    await pool.end();
  }
}

function dashboardPaths(briefingId: string, documentId: string): string[] {
  return [
    "",
    "/overview",
    "/chat",
    "/briefings",
    "/briefings/new",
    `/briefings/${briefingId}`,
    `/documents/${documentId}`,
    "/upload",
    "/consulta",
    "/consulta/grabar",
    "/questionnaire",
    "/enrichment",
    "/enrichment/codes",
    "/enrichment/drugs",
    "/enrichment/genomics",
    "/enrichment/labs",
    "/enrichment/profiles",
    "/enrichment/trials",
    "/ingestion",
    "/ingestion/apple-health",
    "/ingestion/ccd",
    "/ingestion/email",
    "/ingestion/telegram",
    "/ingestion/gdpr/ES",
    "/ingestion/guides/apple-health",
    "/settings",
  ].map((p) => `/dashboard${p}`);
}

// Public pages that print an address (security@godi.ai in their copy).
const PUBLIC_PATHS = ["", "/privacidad", "/terminos", "/profesionales", "/demo", "/signin"];

const NO_TRANSFORM_PATHS = ["/dashboard/settings", "/privacidad", "/terminos", "/profesionales"];

test("pages that print an address ask the edge not to rewrite them, the rest keep gzip", async ({
  context,
}) => {
  const { cookie } = await seedTrialAccount("hdr");
  await context.addCookies([cookie]);
  const get = (path: string) =>
    context.request.get(path, { maxRedirects: 0, headers: { "Accept-Encoding": "gzip" } });
  for (const path of NO_TRANSFORM_PATHS.map((p) => `/es${p}`)) {
    const res = await get(path);
    expect(res.status(), path).toBe(200);
    expect(res.headers()["cache-control"] ?? "", path).toMatch(/no-transform/);
  }
  // no-transform also stops the compression of Next and of Cloudflare, so a
  // page with no address keeps its plain Cache-Control and its gzip.
  for (const path of ["/es", "/es/dashboard", "/es/dashboard/overview"]) {
    const res = await get(path);
    expect(res.status(), path).toBe(200);
    expect(res.headers()["cache-control"] ?? "", path).not.toMatch(/no-transform/);
    expect(res.headers()["content-encoding"], path).toBe("gzip");
  }
});

for (const locale of ["es", "en", "fr"] as const) {
  test(`a trial account hydrates every /${locale} page behind Cloudflare`, async ({
    page,
    context,
  }) => {
    const { cookie, briefingId, documentId } = await seedTrialAccount(locale);
    await context.addCookies([cookie]);
    const edge = await behindCloudflareEmailObfuscation(context);
    const errors = watchHydration(page);

    // Every page is visited before failing, so one run names all of them.
    const failures: Record<string, string[]> = {};
    const paths = [...dashboardPaths(briefingId, documentId), "/billing", ...PUBLIC_PATHS];
    for (const path of paths) {
      const url = `/${locale}${path}`;
      const res = await page.goto(url);
      expect(res?.status(), url).toBeLessThan(400);
      // Not bounced to /signin, /billing or /dashboard: the page under test rendered.
      expect(new URL(page.url()).pathname, url).toBe(url);
      await page.waitForLoadState("networkidle");
      expect(edge.seen.map((u) => new URL(u).pathname), `${url} went through the edge`).toContain(
        url,
      );
      if (errors.length > 0) failures[url] = errors.splice(0);
    }
    expect(failures, "hydration errors").toEqual({});
  });
}
