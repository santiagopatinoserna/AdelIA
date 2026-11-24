import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser } from "@playwright/test";
import { Pool } from "pg";

import es from "../messages/es.json";
import { ask } from "./utils/ask";
import { seedProfile } from "./utils/seed";
import { seedUserAndSessionCookie } from "./utils/session";

// What she noted, asked back on the panel (agent/diary, 2026-11-21). Against
// the REAL API and no model at all: a question about her notes that the rules
// can read is answered in code, so this needs no key and mocks nothing. She
// gets her numbers per day in the answer and the trend as a card under it.

const PHONE = { width: 390, height: 844 };

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
    // observations and profiles cascade from users.
    await pool.query(`DELETE FROM users WHERE id = ANY($1::uuid[])`, [seededUserIds]);
  } finally {
    await pool.end();
  }
});

// `daysAgo` is read in the API's zone (Europe/Madrid, agent/graph.LOCAL_TZ):
// 0 is a moment ago, N is that day at `hour` there, whatever the hour the
// suite runs.
async function note(
  userId: string,
  profileId: string,
  kind: string,
  value: number,
  unit: string,
  daysAgo: number,
  hour = 12,
) {
  const at =
    daysAgo === 0
      ? "now() - interval '1 second'"
      : `(((now() AT TIME ZONE 'Europe/Madrid')::date - ${daysAgo} + time '${hour}:00') ` +
        "AT TIME ZONE 'Europe/Madrid')";
  const pool = pgPool();
  try {
    await pool.query(
      `INSERT INTO observations (user_id, profile_id, kind, value, unit, text, observed_at, source)
       VALUES ($1, $2, $3, $4, $5, $6, ${at}, 'agent')`,
      [userId, profileId, kind, value, unit, `e2e ${kind} ${value}`],
    );
  } finally {
    await pool.end();
  }
}

async function openAs(browser: Browser, tag: string, colorScheme: "light" | "dark" = "light") {
  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-notes-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
  );
  seededUserIds.push(userId);
  const profileId = await seedProfile(userId, { displayName: "Nora", dateOfBirth: "2026-07-10" });
  const context = await browser.newContext({ viewport: PHONE, isMobile: true, hasTouch: true, colorScheme });
  await context.addCookies([cookie]);
  const page = await context.newPage();
  return { context, page, userId, profileId };
}

for (const scheme of ["light", "dark"] as const) {
  test(`es: «¿cuántas tomas lleva esta semana?» answers from her notes, with the trend (${scheme})`, async ({
    browser,
  }) => {
    const { context, page, userId, profileId } = await openAs(browser, `feeds-${scheme}`, scheme);
    await note(userId, profileId, "feed", 120, "ml", 2, 9);
    await note(userId, profileId, "feed", 100, "ml", 2, 13);
    await note(userId, profileId, "feed", 130, "ml", 1, 10);
    await note(userId, profileId, "feed", 110, "ml", 0);

    await page.goto("/es/dashboard");
    await ask(page.getByPlaceholder(es.agent.placeholder), "¿Cuántas tomas lleva esta semana?");

    const answer = page.locator('[data-testid="agent-message"][data-role="assistant"]');
    await expect(answer).toContainText("Tomas, últimos 7 días");
    await expect(answer).toContainText("hoy: 1 toma, 110 ml");
    await expect(answer).toContainText("ayer: 1 toma, 130 ml");
    await expect(answer).toContainText("2 tomas, 220 ml");
    const card = page.locator('[data-testid="trend-card"]:visible');
    await expect(card).toHaveCount(1);
    await expect(card).toHaveAttribute("data-style", "bars");
    await expect(card.getByRole("img")).toHaveAttribute("aria-label", /220 ml.*130 ml.*110 ml/);
    // Nothing of it reaches past the screen of a phone.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.emulateMedia({ reducedMotion: "reduce" });
    const audit = await new AxeBuilder({ page }).include('[data-testid="trend-card"]').analyze();
    expect(audit.violations).toEqual([]);
    if (process.env.E2E_SHOTS) {
      await card.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${process.env.E2E_SHOTS}/notes-feeds-${scheme}.png` });
    }
    await context.close();
  });
}

test("es: «¿cómo va su peso?» draws her weights as a line", async ({ browser }) => {
  const { context, page, userId, profileId } = await openAs(browser, "weight");
  await note(userId, profileId, "weight", 5.1, "kg", 40, 10);
  await note(userId, profileId, "weight", 5.9, "kg", 12, 10);
  await note(userId, profileId, "weight", 6.2, "kg", 2, 10);

  await page.goto("/es/dashboard");
  await ask(page.getByPlaceholder(es.agent.placeholder), "¿Cómo va su peso?");

  const answer = page.locator('[data-testid="agent-message"][data-role="assistant"]');
  await expect(answer).toContainText("6,2 kg");
  await expect(answer).toContainText("+1,1 kg en 38 días (+29 g al día)");
  const card = page.locator('[data-testid="trend-card"]:visible');
  await expect(card).toHaveAttribute("data-style", "line");
  if (process.env.E2E_SHOTS) {
    await card.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${process.env.E2E_SHOTS}/notes-weight.png` });
  }
  await context.close();
});

test("es: nothing noted says so, with no chart", async ({ browser }) => {
  const { context, page } = await openAs(browser, "empty");
  await page.goto("/es/dashboard");
  await ask(page.getByPlaceholder(es.agent.placeholder), "¿Cuántas cacas ha hecho hoy?");
  await expect(page.getByText("Deposiciones: nada anotado hoy. Cuéntamelo cuando pase y lo anoto."))
    .toBeVisible();
  await expect(page.locator('[data-testid="trend-card"]')).toHaveCount(0);
  await context.close();
});
