import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Pool } from "pg";

import { isoMonthsAgo, seedProfile } from "./utils/seed";
import { seedUserAndSessionCookie } from "./utils/session";

// "Hoy con <nombre>": the read-only card at the top of the panel home that
// answers what is due today (vision note 2026-10-22). Computed by GET /today
// from the vaccination calendar, the observations table and the last stored
// plan; rendered server-side by the dashboard page. With nothing due there
// is no card at all: no empty state, no filler.

const PHONE = { width: 390, height: 844 };
// Portable like ux-v2.spec.ts: CI has no Mac home, so the folder is created on the fly.
const SHOTS = join(homedir(), "dev/adelia-design/shots/companion");
mkdirSync(SHOTS, { recursive: true });

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
    // observations, chat_sessions and profiles cascade from users.
    await pool.query(`DELETE FROM users WHERE id = ANY($1::uuid[])`, [seededUserIds]);
  } finally {
    await pool.end();
  }
});

// `day` is read in the API's zone (Europe/Madrid, agent/graph.LOCAL_TZ):
// "yesterday" is yesterday at noon there, whatever the hour the suite runs.
async function seedObservation(
  userId: string,
  profileId: string,
  value: number,
  day: "today" | "yesterday",
) {
  const at =
    day === "today"
      ? "now()"
      : "(((now() AT TIME ZONE 'Europe/Madrid')::date - 1 + time '12:00') AT TIME ZONE 'Europe/Madrid')";
  const pool = pgPool();
  try {
    await pool.query(
      `INSERT INTO observations (user_id, profile_id, kind, value, unit, text, observed_at, source)
       VALUES ($1, $2, 'temperature', $3, '°C', $4, ${at}, 'agent')`,
      [userId, profileId, value, `ha tenido ${value}`],
    );
  } finally {
    await pool.end();
  }
}

async function seedPlan(userId: string) {
  const pool = pgPool();
  try {
    const { rows } = await pool.query(
      // chat_sessions.id and chat_messages.id have no server default (the model
      // fills them in Python), so the rows bring their own.
      `INSERT INTO chat_sessions (id, user_id, title) VALUES (gen_random_uuid(), $1, 'e2e') RETURNING id`,
      [userId],
    );
    const content =
      "## Hoy\n- Ofrécele el pecho más a menudo [ev_1].\n\n" +
      "## No olvides\n- Apunta cada toma hasta mañana [ev_2].\n";
    await pool.query(
      `INSERT INTO chat_messages (id, session_id, user_id, role, content)
       VALUES (gen_random_uuid(), $1, $2, 'assistant', $3)`,
      [rows[0].id, userId, content],
    );
  } finally {
    await pool.end();
  }
}

async function openAs(browser: Browser, tag: string, colorScheme: "light" | "dark") {
  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-today-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
  );
  seededUserIds.push(userId);
  const context = await browser.newContext({
    viewport: PHONE,
    isMobile: true,
    hasTouch: true,
    colorScheme,
  });
  await context.addCookies([cookie]);
  const page = await context.newPage();
  return { context, page, userId };
}

for (const scheme of ["light", "dark"] as const) {
  test(`today card: vaccines, the reading and the plan line at 390px (${scheme})`, async ({
    browser,
  }) => {
    const { context, page, userId } = await openAs(browser, scheme, scheme);
    // 3 months old with no dose on record: the 2-month doses are overdue.
    const profileId = await seedProfile(userId, {
      displayName: "Nora",
      dateOfBirth: isoMonthsAgo(3),
    });
    await seedObservation(userId, profileId, 37.2, "yesterday");
    await seedObservation(userId, profileId, 37.8, "today");
    await seedPlan(userId);

    await page.goto("/es/dashboard");
    const card = page.getByRole("region", { name: "Hoy con Nora" });
    await expect(card).toBeVisible();
    await expect(card.getByRole("heading", { name: "Hoy con Nora" })).toBeVisible();
    const items = card.getByRole("listitem");
    await expect(items).toHaveCount(3);
    await expect(items.nth(0)).toContainText("Hexavalente");
    await expect(items.nth(0)).toContainText("2 meses");
    await expect(items.nth(1)).toHaveText("Temperatura: ayer 37,2 °C, hoy 37,8 °C.");
    await expect(items.nth(2)).toHaveText("Apunta cada toma hasta mañana.");
    // The card is the first thing under the greeting: above the showcase.
    const cardTop = await card.evaluate((el) => el.getBoundingClientRect().top);
    expect(cardTop).toBeLessThan(PHONE.height / 2);

    // No sideways scroll, and no card wider than the phone.
    const w = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(w.scrollWidth).toBe(w.clientWidth);
    const box = await card.boundingBox();
    expect(box && box.x + box.width).toBeLessThanOrEqual(PHONE.width);

    await page.waitForLoadState("networkidle").catch(() => {});
    await page.evaluate(() =>
      Promise.race([
        Promise.allSettled(document.getAnimations().map((a) => a.finished)),
        new Promise((resolve) => setTimeout(resolve, 1500)),
      ]),
    );
    const results = await new AxeBuilder({ page }).analyze();
    const blocking = results.violations.filter((v) =>
      ["serious", "critical"].includes(v.impact ?? ""),
    );
    expect(blocking.map((v) => v.id)).toEqual([]);
    await page.screenshot({ path: `${SHOTS}/today-card-390-${scheme}.png` });
    await context.close();
  });
}

test("today card: nothing due, no card", async ({ browser }) => {
  const { context, page, userId } = await openAs(browser, "empty", "light");
  // No date of birth, no reading, no plan: nothing to say, so nothing is drawn.
  await seedProfile(userId, { displayName: "Nora", dateOfBirth: null });
  await page.goto("/es/dashboard");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: /^Hoy/ })).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/today-card-390-none.png` });
  await context.close();
});
