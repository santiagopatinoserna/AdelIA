import { Pool } from "pg";
import { expect, test } from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";

// Cancelling a subscription must not close a mother's own records.
//
// When the paywall moved from the web layout into the API, the API gate first
// went on six APIRouter objects and the dashboard gate went fail-closed. Both
// were too wide, and together they walled her in: every read answered 402, and
// /dashboard/settings — the only screen with "export my data" (GDPR art. 20)
// and "delete my account" (art. 17) — sat under the same redirect as the
// product, while /billing linked nowhere back. The only door left was the raw
// API.
//
// The gate now lives in dashboard/(paid)/layout.tsx, so settings is outside
// it, and /billing carries a visible link to it. This walks that journey.

async function cancel(userId: string) {
  const pool = new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? 5434),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
  await pool.query(
    "UPDATE users SET subscription_status = 'canceled' WHERE id = $1",
    [userId],
  );
  await pool.end();
}

test("a canceled account still reaches export and delete, with the chrome", async ({
  browser,
}) => {
  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-gdpr-${Date.now()}@adelia.test`,
  );
  await cancel(userId);
  const context = await browser.newContext();
  await context.addCookies([cookie]);
  const page = await context.newPage();

  // The paid dashboard still sends her to /billing: nothing was opened up.
  await page.goto("/es/dashboard");
  await expect(page).toHaveURL(/\/es\/billing$/);

  // And /billing, where the redirect deposits her, is no longer a dead end.
  const link = page.getByRole("link", { name: "Exportar o borrar mis datos" });
  await expect(link).toBeVisible();
  await link.click();

  // Settings renders — with the dashboard header, not stripped bare — and
  // holds the export door.
  await expect(page).toHaveURL(/\/es\/dashboard\/settings$/);
  await expect(page.getByRole("banner")).toBeVisible();
  await expect(
    page.locator('a[href="/api/backend/users/me/export"]'),
  ).toBeVisible();

  await context.close();
});
