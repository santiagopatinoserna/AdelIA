import { randomUUID } from "node:crypto";

import { expect, test, type Browser } from "@playwright/test";
import { Pool } from "pg";

import es from "../messages/es.json";
import { seedProfile } from "./utils/seed";
import { seedUserAndSessionCookie } from "./utils/session";

// Historial is her child's record, month by month (GET /history, 2026-11-25):
// what she noted, her documents and her recordings in one list, by day, back
// to the month the child was born (docs/specs/ADELIA_SIMPLE.md). It listed the
// account's documents only: a note she confirmed in the panel came back through
// a question and nowhere else, and with notes and no document the page still
// said "Bienvenida a AdelIA, sube tu primer informe" (QA 2026-11-12). Against
// the real API, no mocks.

const PHONE = { width: 390, height: 844 };
const BORN = "2026-07-10";
const ZONE = "Europe/Madrid";

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
    // observations and profiles cascade from users; documents do not.
    await pool.query(`DELETE FROM documents WHERE user_id = ANY($1::uuid[])`, [seededUserIds]);
    await pool.query(`DELETE FROM users WHERE id = ANY($1::uuid[])`, [seededUserIds]);
  } finally {
    await pool.end();
  }
});

async function sql(text: string, values: unknown[]) {
  const pool = pgPool();
  try {
    return (await pool.query(text, values)).rows;
  } finally {
    await pool.end();
  }
}

// A reading an hour ago, with its hour, as the panel stores a confirmed card.
const noteAnHourAgo = (userId: string, profileId: string, kind: string, value: number,
  unit: string) => sql(
  `INSERT INTO observations (user_id, profile_id, kind, value, unit, text, observed_at, source)
   VALUES ($1, $2, $3, $4, $5, 'e2e', now() - interval '1 hour', 'agent')`,
  [userId, profileId, kind, value, unit],
);

async function openAs(browser: Browser, tag: string) {
  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-historial-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`,
  );
  seededUserIds.push(userId);
  const context = await browser.newContext({ viewport: PHONE, isMobile: true, hasTouch: true });
  await context.addCookies([cookie]);
  return { context, page: await context.newPage(), userId };
}

const ymd = (d: Date) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: ZONE, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(d);
const dayTitle = (day: string) =>
  new Intl.DateTimeFormat("es", { dateStyle: "long", timeZone: "UTC" })
    .format(new Date(`${day}T12:00:00Z`));
// A tap that renders a page on the server: under the full suite's three workers
// that can take more than Playwright's 5 s, as other specs allow for
// (diary.spec 20 s, guest-journey 30 s). The month links are plain links: the
// soft navigation they replaced fetched its page and never committed, 6 taps
// of 8 (see the page).
const NAVIGATION = { timeout: 30_000 };
const monthName = (ym: string) =>
  new Intl.DateTimeFormat("es", { month: "short", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${ym}-15T12:00:00Z`));

test("Historial lists her notes and documents by day, back to the month she was born", async ({
  browser,
}) => {
  const { context, page, userId } = await openAs(browser, "record");
  const nora = await seedProfile(userId, { displayName: "Nora", dateOfBirth: BORN });
  const adel = await seedProfile(userId, { displayName: "Adel", dateOfBirth: BORN, isDefault: false });
  await noteAnHourAgo(userId, nora, "feed", 120, "ml");
  await noteAnHourAgo(userId, adel, "temperature", 39, "°C");
  // «Al nacer pesó 3,2 kg»: the day she was born, no hour (agent/record, timed false).
  await sql(
    `INSERT INTO observations (user_id, profile_id, kind, value, unit, text, observed_at, timed, source)
     VALUES ($1, $2, 'weight', 3.2, 'kg', 'al nacer pesó 3,2 kg',
             ($3::date + time '12:00') AT TIME ZONE 'Europe/Madrid', false, 'agent')`,
    [userId, nora, BORN],
  );
  const [doc] = await sql(
    `INSERT INTO documents (id, user_id, profile_id, source, mime_type, s3_key, raw_text, processed_at, created_at)
     VALUES (gen_random_uuid(), $1, $2, 'web', 'application/pdf', $3, 'texto', now(), now() - interval '1 hour')
     RETURNING id`,
    [userId, nora, `users/${userId}/${randomUUID()}-analitica.pdf`],
  );

  await page.goto("/es/dashboard/overview");
  const main = page.getByRole("main");
  // Whose record: the default child, by name.
  await expect(main.getByRole("heading", { level: 1 })).toHaveText(
    es.dashboard.historyTitle.replace("{name}", "Nora"),
  );
  await expect(main).not.toContainText(es.dashboard.welcomeTitle);

  // Today: the feed with its hour, in the card's words, and the report.
  const today = main.getByRole("region", { name: dayTitle(ymd(new Date(Date.now() - 3600_000))) });
  await expect(today.getByRole("listitem").filter({ hasText: "Toma: 120 ml" }))
    .toHaveText(/^\d{2}:\d{2}Toma: 120 ml$/);
  const report = today.locator(`a[href="/es/dashboard/documents/${doc.id}"]`);
  await expect(report).toContainText("analitica.pdf");
  // Her sibling's fever is Adel's, not Nora's.
  await expect(main).not.toContainText("39 °C");

  // From the document, "Historial" leads back here (it led to the home).
  await report.click();
  await expect(page).toHaveURL(new RegExp(`/es/dashboard/documents/${doc.id}$`), NAVIGATION);
  await page.getByRole("main").getByRole("link", { name: es.dashboard.title, exact: true }).click();
  await expect(page).toHaveURL(/\/es\/dashboard\/overview$/, NAVIGATION);

  // The months that hold something: this one, current, and the month she was born.
  const months = main.getByRole("navigation", { name: es.dashboard.monthsLabel });
  const links = months.getByRole("link");
  await expect(links).toHaveCount(2);
  await expect(links.first()).toHaveAttribute("aria-current", "page");
  const born = links.last();
  await expect(born).toHaveText(monthName(BORN.slice(0, 7)));
  await born.click();
  await expect(page).toHaveURL(
    new RegExp(`/es/dashboard/overview\\?month=${BORN.slice(0, 7)}$`), NAVIGATION,
  );
  const birthDay = main.getByRole("region", { name: dayTitle(BORN) });
  // The day she named and no hour she never gave.
  await expect(birthDay.getByRole("listitem")).toHaveText(["Peso: 3,2 kg"]);
  await expect(birthDay.locator("time")).toHaveCount(0);
  await expect(months.getByRole("link", { name: monthName(BORN.slice(0, 7)) }))
    .toHaveAttribute("aria-current", "page");

  const w = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(w.scrollWidth, "Historial scrolls sideways").toBe(w.clientWidth);
  await context.close();
});

test("a note alone is a record: Historial shows it, not the first-run welcome", async ({
  browser,
}) => {
  const { context, page, userId } = await openAs(browser, "note-only");
  const nora = await seedProfile(userId, { displayName: "Nora", dateOfBirth: BORN });
  await noteAnHourAgo(userId, nora, "temperature", 37.8, "°C");

  await page.goto("/es/dashboard/overview");
  const main = page.getByRole("main");
  await expect(main.getByRole("listitem").filter({ hasText: "Temperatura: 37,8 °C" }))
    .toBeVisible();
  await expect(main).not.toContainText(es.dashboard.welcomeTitle);
  // A single month needs no row of months.
  await expect(main.getByRole("navigation", { name: es.dashboard.monthsLabel })).toHaveCount(0);
  await context.close();
});
