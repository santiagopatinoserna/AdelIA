import { Pool } from "pg";
import { expect, test } from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";

// Audit 4.7. Two things used to be true at once: the first screen after the
// magic link was Stripe Checkout with a card required, and there was no link
// anywhere inside the app towards billing, so cancelling or changing a card
// meant writing to support.
//
// Now a brand-new account walks straight into the panel (the trial is derived
// from users.created_at, nothing is written at signup), and Settings carries a
// "Suscripción" section whose button is one click from Stripe.

function pool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

/** A brand-new account: never through Stripe, never asked about the baby. */
async function seedFreshAccount(email: string) {
  const seeded = await seedUserAndSessionCookie(email);
  const db = pool();
  await db.query(
    `UPDATE users
        SET subscription_status = 'none',
            trial_end = NULL,
            stripe_customer_id = NULL,
            created_at = now(),
            onboarded_at = now()
      WHERE id = $1`,
    [seeded.userId],
  );
  await db.end();
  return seeded;
}

test("a brand-new account reaches the panel without passing through Stripe", async ({
  browser,
}) => {
  const { cookie } = await seedFreshAccount(`e2e-trial-${Date.now()}@adelia.test`);
  const context = await browser.newContext();
  await context.addCookies([cookie]);
  const page = await context.newPage();

  await page.goto("/es/dashboard");

  // Not /billing, and not /signin: the panel itself.
  await expect(page).toHaveURL(/\/es\/dashboard$/);
  await context.close();
});

test("Settings carries a Suscripción section that reaches Stripe in one click", async ({
  browser,
}) => {
  const { cookie } = await seedFreshAccount(`e2e-sub-${Date.now()}@adelia.test`);
  const context = await browser.newContext();
  await context.addCookies([cookie]);
  const page = await context.newPage();

  await page.goto("/es/dashboard/settings");
  const section = page.locator("section", { hasText: "Suscripción" }).first();
  await expect(section).toBeVisible();
  // Inside the free trial, with no Stripe customer yet: the one click goes to
  // /billing, not to a portal button that would answer 400.
  await expect(section.getByText(/prueba gratuita/i)).toBeVisible();
  const cta = section.getByRole("link", { name: /Ver planes y suscribirme/ });
  await expect(cta).toBeVisible();
  await cta.click();
  await expect(page).toHaveURL(/\/es\/billing/);
  await context.close();
});

test("/billing during the card-free trial offers subscribing, not a dead portal", async ({
  browser,
}) => {
  const { cookie } = await seedFreshAccount(`e2e-billing-${Date.now()}@adelia.test`);
  const context = await browser.newContext();
  await context.addCookies([cookie]);
  const page = await context.newPage();

  await page.goto("/es/billing");

  // The trial is real and named as such, and it does NOT claim a first
  // charge date, because there is no Stripe subscription behind it.
  await expect(
    page.getByRole("heading", { name: "Tu prueba gratuita está en marcha" }),
  ).toBeVisible();
  await expect(page.getByText(/Primer cobro/)).toHaveCount(0);
  // No Stripe customer yet: the portal would answer 400, so the offer is to
  // subscribe instead.
  await expect(page.getByRole("button", { name: "Suscribirme ahora" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Gestionar suscripción/ })).toHaveCount(0);
  await context.close();
});

test("the funnel counts a visit and an Empezar press, and sets no cookie", async ({
  page,
  context,
}) => {
  const before = await page.request.post("/api/funnel/visit");
  expect(before.status()).toBe(204);
  // The counter endpoint must never hand a visitor an identity.
  expect(before.headers()["set-cookie"]).toBeUndefined();

  const db = pool();
  const { rows: start } = await db.query(
    "SELECT count FROM funnel_counters WHERE event = 'start' AND day = (now() at time zone 'utc')::date",
  );
  const startBefore = Number(start[0]?.count ?? 0);

  await page.goto("/es");
  await page.getByRole("link", { name: "Empezar", exact: true }).first().click();
  await page.waitForURL(/\/es\/(dashboard|signin|onboarding)/, { timeout: 20_000 });

  // The beacon rides with keepalive, so give it a moment to land.
  await expect
    .poll(
      async () => {
        const { rows } = await db.query(
          "SELECT count FROM funnel_counters WHERE event = 'start' AND day = (now() at time zone 'utc')::date",
        );
        return Number(rows[0]?.count ?? 0);
      },
      { timeout: 15_000 },
    )
    .toBeGreaterThan(startBefore);
  await db.end();

  // Nothing the funnel did put a cookie in this browser.
  const names = (await context.cookies()).map((c) => c.name);
  expect(names.filter((n) => /funnel|analytic|_ga|track/i.test(n))).toEqual([]);
});
