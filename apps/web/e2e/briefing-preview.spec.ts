import { expect, test } from "@playwright/test";
import { Pool } from "pg";

import { seedUserAndSessionCookie } from "./utils/session";

// The stored report HTML is the shared page, whose <link> now points at the
// API's stylesheet under /s/ (prod journey 2026-11-06). Injected as is into
// the in-app preview it would load that sheet into the whole dashboard, and
// its generic classes (.section, .citation) would restyle the app.

function pgPool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

test("the in-app report preview does not pull in the shared page's stylesheet", async ({ page, context }) => {
  const { userId, cookie } = await seedUserAndSessionCookie(`e2e-preview-${Date.now()}@example.com`);
  const pool = pgPool();
  let id: string;
  try {
    const { rows } = await pool.query(
      `INSERT INTO briefings (user_id, target_specialty, status, html_render, completed_at, payload)
       VALUES ($1, 'pediatrics', 'ready', $2, now(), '{}'::jsonb) RETURNING id`,
      [userId, '<!DOCTYPE html><html><head><link rel="stylesheet" href="/s/_assets/briefing.css">'
        + '</head><body class="briefing"><h1>Informe de Nora</h1></body></html>'],
    );
    id = rows[0].id;
    await context.addCookies([cookie]);
    await page.goto(`/es/dashboard/briefings/${id}`);
    await expect(page.getByText("Informe de Nora")).toBeVisible();
    await expect(page.locator('link[href*="briefing.css"]')).toHaveCount(0);
  } finally {
    await pool.query(`DELETE FROM briefings WHERE user_id = $1`, [userId]);
    await pool.query(`DELETE FROM users WHERE id = $1`, [userId]);
    await pool.end();
  }
});
