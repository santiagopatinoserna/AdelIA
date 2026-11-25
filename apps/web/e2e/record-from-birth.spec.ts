import { expect, test, type Browser } from "@playwright/test";
import { Pool } from "pg";

import es from "../messages/es.json";
import { ask } from "./utils/ask";
import { seedProfile } from "./utils/seed";
import { seedUserAndSessionCookie } from "./utils/session";

// Her record from birth (agent/record, 2026-11-24). «Al nacer pesó 3,2 kg» used
// to be saved as today's weight, four kilos down on her curve. Against the REAL
// API and no model: the rules route the line, read the day, the card shows the
// day she named and no hour she did not say, and her curve then starts there.

const PHONE = { width: 390, height: 844 };
const BORN = "2026-07-10";

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

async function openAs(browser: Browser) {
  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-birth-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
  );
  seededUserIds.push(userId);
  const profileId = await seedProfile(userId, { displayName: "Nora", dateOfBirth: BORN });
  const context = await browser.newContext({ viewport: PHONE, isMobile: true, hasTouch: true });
  await context.addCookies([cookie]);
  return { context, page: await context.newPage(), userId, profileId };
}

// The card writes the year once it is not this one (12/10/26).
const birthDay = `10/07${new Date().getFullYear() === 2026 ? "" : "/26"}`;

test("es: «Al nacer pesó 3,2 kg» is noted on the day she was born, and her curve starts there", async ({
  browser,
}) => {
  const { context, page, userId, profileId } = await openAs(browser);
  await page.goto("/es/dashboard");
  await ask(page.getByPlaceholder(es.agent.placeholder), "Al nacer pesó 3,2 kg");

  const card = page.locator('[data-testid="confirm-card"]:visible');
  await expect(card.getByTestId("confirm-body")).toHaveText(`Peso: 3,2 kg, el ${birthDay}`);
  await card.getByRole("button", { name: es.agent.confirmYes, exact: true }).click();
  await expect(page.getByText(`Anotado: 3,2 kg, el ${birthDay}.`)).toBeVisible();

  const pool = pgPool();
  try {
    const { rows } = await pool.query(
      `SELECT value, timed, (observed_at AT TIME ZONE 'Europe/Madrid')::date::text AS day
         FROM observations WHERE user_id = $1`,
      [userId],
    );
    expect(rows).toEqual([{ value: 3.2, timed: false, day: BORN }]);
    // A weighing of two days ago, so the curve has two ends.
    await pool.query(
      `INSERT INTO observations (user_id, profile_id, kind, value, unit, text, observed_at, source)
       VALUES ($1, $2, 'weight', 6.1, 'kg', 'pesa 6,1',
               ((now() AT TIME ZONE 'Europe/Madrid')::date - 2 + time '10:00')
                 AT TIME ZONE 'Europe/Madrid', 'agent')`,
      [userId, profileId],
    );
  } finally {
    await pool.end();
  }

  // After an answer the field invites a follow-up: found by its label.
  await ask(page.getByLabel(es.agent.inputLabel), "¿Cómo va su peso?");
  const answer = page.locator('[data-testid="agent-message"][data-role="assistant"]').last();
  await expect(answer).toContainText(`${birthDay}: 3,2 kg`);
  await expect(answer).toContainText(new RegExp(`Desde el ${birthDay}: \\+2,9 kg en \\d+ días`));
  await expect(answer).not.toContainText("12:00");
  await expect(page.locator('[data-testid="trend-card"]:visible')).toHaveAttribute("data-style", "line");
  if (process.env.E2E_SHOTS) {
    await page.screenshot({ path: `${process.env.E2E_SHOTS}/record-from-birth.png` });
  }
  await context.close();
});
