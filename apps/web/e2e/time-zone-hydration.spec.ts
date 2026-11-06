import { expect, test, type Page } from "@playwright/test";
import { Pool } from "pg";

import { isoMonthsAgo, seedProfile } from "./utils/seed";
import { seedUserAndSessionCookie } from "./utils/session";

// React #418 in production (prod journey 2026-11-06, 01:05 in Madrid): the
// server printed a date in its own zone (the container runs in UTC) and the
// phone printed it in Europe/Madrid, so the text differed and hydration
// failed on /dashboard/briefings and /dashboard/settings. Every row here is
// stamped at 23:30 UTC, which is already the next day in Madrid: a formatter
// without a fixed zone writes two different days.
//
// To reproduce, the web server must run in UTC, as the production container
// and the CI runner do (`TZ=UTC pnpm exec next start`). The browser is pinned
// to Madrid below.

test.use({ timezoneId: "Europe/Madrid", locale: "es-ES", viewport: { width: 390, height: 844 } });

function pgPool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

// Yesterday at 23:30 UTC, and the trial ending ten days later at the same
// minute: the shape of the account that broke, made before midnight in UTC.
const LATE_UTC = "(date_trunc('day', now() AT TIME ZONE 'UTC') - interval '30 minutes') AT TIME ZONE 'UTC'";

const seededUserIds: string[] = [];

test.afterAll(async () => {
  if (seededUserIds.length === 0) return;
  const pool = pgPool();
  try {
    await pool.query(`DELETE FROM documents WHERE user_id = ANY($1::uuid[])`, [seededUserIds]);
    await pool.query(`DELETE FROM briefings WHERE user_id = ANY($1::uuid[])`, [seededUserIds]);
    await pool.query(`DELETE FROM users WHERE id = ANY($1::uuid[])`, [seededUserIds]);
  } finally {
    await pool.end();
  }
});

function watchHydration(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (/hydrat|#418|#423|#425|did not match/i.test(text)) errors.push(`console: ${text}`);
  });
  return errors;
}

test("dates read the same on the server in UTC and on a phone in Madrid", async ({
  page,
  context,
}) => {
  const email = `e2e-tz-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
  const { userId, cookie } = await seedUserAndSessionCookie(email);
  seededUserIds.push(userId);
  const profileId = await seedProfile(userId, {
    displayName: "Nora",
    dateOfBirth: isoMonthsAgo(4),
  });

  const pool = pgPool();
  let briefingId: string;
  let documentId: string;
  let seededAt: Date;
  try {
    await pool.query(
      `UPDATE users SET trial_end = ${LATE_UTC} + interval '10 days' WHERE id = $1`,
      [userId],
    );
    const b = await pool.query(
      `INSERT INTO briefings (user_id, profile_id, target_specialty, status, html_render,
                              created_at, completed_at, payload)
       VALUES ($1, $2, 'pediatrics', 'ready', '<h1>Informe de Nora</h1>',
               ${LATE_UTC}, ${LATE_UTC}, '{}'::jsonb)
       RETURNING id, created_at`,
      [userId, profileId],
    );
    briefingId = b.rows[0].id;
    seededAt = b.rows[0].created_at;
    // processed_at set: a row without it is requeued as a real pipeline by
    // the next API boot (CLAUDE.md).
    const d = await pool.query(
      `INSERT INTO documents (id, user_id, profile_id, source, mime_type, s3_key, raw_text,
                              created_at, processed_at)
       VALUES (gen_random_uuid(), $1, $2, 'manual', 'application/pdf', $3,
               'Documento de prueba e2e.', ${LATE_UTC}, ${LATE_UTC})
       RETURNING id`,
      [userId, profileId, `e2e/tz-${Date.now()}.pdf`],
    );
    documentId = d.rows[0].id;
  } finally {
    await pool.end();
  }

  await context.addCookies([cookie]);
  const errors = watchHydration(page);

  for (const path of [
    "/es/dashboard/briefings",
    `/es/dashboard/briefings/${briefingId}`,
    "/es/dashboard/settings",
    "/es/dashboard/overview",
    `/es/dashboard/documents/${documentId}`,
    "/es/dashboard",
    "/es/billing",
  ]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    expect(errors, `hydration errors on ${path}`).toEqual([]);
  }

  // The day she reads is the Madrid day: 23:30 UTC is already 00:30 of the
  // next one there, on the server's render and on the phone's alike.
  const madridDay = new Intl.DateTimeFormat("es", {
    timeZone: "Europe/Madrid",
    day: "numeric",
    month: "short",
  }).format(seededAt);
  await page.goto("/es/dashboard/briefings");
  // The route's loading skeleton is a second <main aria-busy="true"> until the
  // page streams in; reading "main" before it leaves is a strict-mode error
  // (CI, 2026-11-06, run 42155414490). Wait for it, then read the page's own.
  await expect(page.locator('main[aria-busy="true"]')).toHaveCount(0);
  await expect(page.locator("main")).toContainText(madridDay);
});
