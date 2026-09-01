import { expect, test } from "@playwright/test";
import { Pool } from "pg";

import { seedUserAndSessionCookie } from "./utils/session";

// Audit 4.3: between the magic link and the first useful pixel there was a
// credit card and not one question about the baby, so the age-gated clinical
// rules (fever under 3 months, paediatric lab bands, growth percentiles, the
// briefing header) all ran without a date of birth.
//
// seedUserAndSessionCookie stamps `onboarded_at`, because a seeded user stands
// for an existing account; these tests clear it to get a genuinely new one.

function pgPool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

async function makeBrandNewAccount(tag: string) {
  const { userId, cookie } = await seedUserAndSessionCookie(
    `e2e-onboarding-${tag}-${Date.now()}@adelia.test`,
  );
  const db = pgPool();
  await db.query("UPDATE users SET onboarded_at = NULL WHERE id = $1", [userId]);
  await db.end();
  return { userId, cookie };
}

async function readProfile(userId: string) {
  const db = pgPool();
  const { rows } = await db.query(
    `SELECT display_name, relationship, date_of_birth, sex, is_default
       FROM profiles WHERE user_id = $1 AND deleted_at IS NULL
       ORDER BY created_at DESC LIMIT 1`,
    [userId],
  );
  const { rows: userRows } = await db.query(
    "SELECT onboarded_at FROM users WHERE id = $1",
    [userId],
  );
  await db.end();
  return { profile: rows[0], onboardedAt: userRows[0]?.onboarded_at };
}

test("a brand new account meets the three baby questions before the panel", async ({
  browser,
}) => {
  const { userId, cookie } = await makeBrandNewAccount("gate");
  const context = await browser.newContext();
  await context.addCookies([cookie]);
  const page = await context.newPage();

  await page.goto("/es/dashboard");
  await expect(page).toHaveURL(/\/es\/onboarding$/);

  // Three fields, and nothing else to fill in.
  await expect(page.getByLabel("Nombre del bebé")).toBeVisible();
  await expect(page.getByLabel("Fecha de nacimiento")).toBeVisible();
  await expect(page.getByLabel("Sexo")).toBeVisible();

  await page.getByLabel("Nombre del bebé").fill("Adel");
  await page.getByLabel("Fecha de nacimiento").fill("2025-03-01");
  await page.getByLabel("Sexo").selectOption("M");
  await page.getByRole("button", { name: "Guardar y entrar" }).click();

  await page.waitForURL(/\/es\/dashboard$/, { timeout: 30_000 });

  const { profile, onboardedAt } = await readProfile(userId);
  expect(profile.relationship).toBe("child");
  expect(profile.display_name).toBe("Adel");
  expect(profile.is_default).toBe(true);
  expect(onboardedAt).not.toBeNull();

  // Asked once: coming back does not put the screen in her way again.
  await page.goto("/es/dashboard");
  await expect(page).toHaveURL(/\/es\/dashboard$/);
  await context.close();
});

test("the screen is skippable and stays skipped", async ({ browser }) => {
  const { userId, cookie } = await makeBrandNewAccount("skip");
  const context = await browser.newContext();
  await context.addCookies([cookie]);
  const page = await context.newPage();

  await page.goto("/es/dashboard");
  await expect(page).toHaveURL(/\/es\/onboarding$/);
  await page.getByRole("button", { name: "Ahora no" }).click();
  await page.waitForURL(/\/es\/dashboard$/, { timeout: 30_000 });

  const { onboardedAt } = await readProfile(userId);
  expect(onboardedAt).not.toBeNull();

  await page.goto("/es/dashboard");
  await expect(page).toHaveURL(/\/es\/dashboard$/);
  await context.close();
});

test("the screen speaks the three languages", async ({ browser }) => {
  for (const [locale, heading] of [
    ["es", /De quién vamos a cuidar/],
    ["en", /Who are we looking after/],
    ["fr", /De qui allons-nous prendre soin/],
  ] as const) {
    const { cookie } = await makeBrandNewAccount(`i18n-${locale}`);
    const context = await browser.newContext();
    await context.addCookies([cookie]);
    const page = await context.newPage();
    await page.goto(`/${locale}/dashboard`);
    await expect(page).toHaveURL(new RegExp(`/${locale}/onboarding$`));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
    await context.close();
  }
});
