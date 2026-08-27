import { randomUUID } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";
import { Pool } from "pg";

import { seedUserAndSessionCookie } from "./utils/session";

// Daily diary (Telegram-first) regression, UI side only: no Telegram, no
// Mistral. Everything the cards and titles depend on is seeded straight in
// Postgres (telegram_links row, diary Document with metadata.diary_date),
// the same rows the bot writes through adelia.services.telegram_diary.
// The api under test must run with a (dummy) TELEGRAM_BOT_TOKEN: without
// it the suggestions hide both diary cards (the bot would be dead).

const RAIL_LABEL = "Para ti"; // agent.suggestionsTitle (es)
const CARD_LINK = "Diario por Telegram";
const CARD_TODAY = "¿Cómo ha ido hoy?";
const CARD_ALL_DONE = "Todo al día";

function pgPool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

async function withPg<T>(fn: (pool: Pool) => Promise<T>): Promise<T> {
  const pool = pgPool();
  try {
    return await fn(pool);
  } finally {
    await pool.end();
  }
}

// The api computes "today" in Europe/Madrid (settings.diary_reminder_tz).
// Mirror it so the "no card once today's entry exists" check also holds
// around midnight UTC.
function todayIsoMadrid(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Madrid",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

// dashboard.diaryDocTitle = "Diario del {date}", date rendered by the web
// with Intl long style from `${diary_date}T12:00:00`.
function expectedDiaryTitle(iso: string): string {
  const long = new Intl.DateTimeFormat("es", { dateStyle: "long" }).format(
    new Date(`${iso}T12:00:00`),
  );
  return `Diario del ${long}`;
}

function uniqueEmail(tag: string): string {
  return `e2e-diary-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@adelia.test`;
}

// Rows seeded by this spec are removed in afterAll: a leftover
// telegram_links row makes every daily reminder of a dev api call Telegram
// for a chat that does not exist.
const seededUserIds: string[] = [];

async function linkTelegram(userId: string): Promise<number> {
  // telegram_links.chat_id is UNIQUE: a random 12-digit id keeps runs apart.
  const chatId = 100_000_000_000 + Math.floor(Math.random() * 899_999_999_999);
  await withPg((pool) =>
    pool.query(
      `INSERT INTO telegram_links (user_id, chat_id, username) VALUES ($1, $2, 'e2e_diary')`,
      [userId, chatId],
    ),
  );
  return chatId;
}

test.afterAll(async () => {
  if (seededUserIds.length === 0) return;
  await withPg(async (pool) => {
    // documents.user_id has no ON DELETE; chunks/entities cascade from documents,
    // telegram_links/profiles cascade from users.
    await pool.query(`DELETE FROM documents WHERE user_id = ANY($1::uuid[])`, [seededUserIds]);
    await pool.query(`DELETE FROM users WHERE id = ANY($1::uuid[])`, [seededUserIds]);
  });
});

async function insertDiaryDocument(userId: string, diaryDate: string): Promise<string> {
  const rendered = `Diario de Adel, ${diaryDate}.\n\nHa dormido bien y ha comido de todo.`;
  const s3Key = `users/${userId}/${randomUUID()}-diario-${diaryDate}.txt`;
  const { rows } = await withPg((pool) =>
    pool.query(
      `INSERT INTO documents (id, user_id, source, mime_type, s3_key, raw_text, metadata, processed_at)
       VALUES (gen_random_uuid(), $1, 'manual', 'text/plain', $2, $3, $4::jsonb, now())
       RETURNING id`,
      [userId, s3Key, rendered, JSON.stringify({ diary_date: diaryDate, channel: "telegram" })],
    ),
  );
  return (rows[0] as { id: string }).id;
}

// Desktop viewport (Playwright default 1280x720): the cards live in the
// aside rail; the inline mobile copy of the same cards is display:none.
function suggestionRail(page: Page) {
  return page.getByRole("complementary", { name: RAIL_LABEL });
}

test.describe("daily diary (Telegram) UI", () => {
  test("unlinked user gets the link-Telegram card; Enlazar opens the Telegram page", async ({
    page,
    context,
  }) => {
    const { userId, cookie } = await seedUserAndSessionCookie(uniqueEmail("unlinked"));
    seededUserIds.push(userId);
    await context.addCookies([cookie]);
    await page.goto("/es/dashboard");

    const rail = suggestionRail(page);
    await expect(rail.getByText(CARD_LINK, { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(rail.getByText(CARD_TODAY, { exact: true })).toHaveCount(0);

    await rail.getByRole("button", { name: "Enlazar", exact: true }).click();
    await expect(page).toHaveURL(/\/es\/dashboard\/ingestion\/telegram$/, { timeout: 20_000 });
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Enlazar Telegram");
  });

  test("linked user without today's entry gets the daily card; Abrir Telegram opens the bot", async ({
    page,
    context,
  }) => {
    const { userId, cookie } = await seedUserAndSessionCookie(uniqueEmail("linked"));
    seededUserIds.push(userId);
    await linkTelegram(userId);
    await context.addCookies([cookie]);
    // Never leave the app: capture window.open instead of opening t.me.
    await page.addInitScript(() => {
      const w = window as unknown as { __opened: string[]; open: typeof window.open };
      w.__opened = [];
      w.open = ((url?: string | URL) => {
        w.__opened.push(String(url));
        return null;
      }) as typeof window.open;
    });
    await page.goto("/es/dashboard");

    const rail = suggestionRail(page);
    await expect(rail.getByText(CARD_TODAY, { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(rail.getByText(CARD_LINK, { exact: true })).toHaveCount(0);

    await rail.getByRole("button", { name: "Abrir Telegram", exact: true }).click();
    await expect
      .poll(() => page.evaluate(() => (window as unknown as { __opened: string[] }).__opened))
      .toEqual([expect.stringContaining("https://t.me/")]);
    await expect(page).toHaveURL(/\/es\/dashboard$/);
  });

  test("diary document is titled by its day and silences the daily card", async ({
    page,
    context,
  }) => {
    const { userId, cookie } = await seedUserAndSessionCookie(uniqueEmail("doc"));
    seededUserIds.push(userId);
    await linkTelegram(userId);
    const today = todayIsoMadrid();
    const docId = await insertDiaryDocument(userId, today);
    const title = expectedDiaryTitle(today);
    await context.addCookies([cookie]);

    // Overview: the document card shows the day, not the generated filename.
    await page.goto("/es/dashboard/overview");
    await expect(page.getByText(title, { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(`diario-${today}.txt`)).toHaveCount(0);

    // Detail: same title in the h1, diary text rendered.
    await page.goto(`/es/dashboard/documents/${docId}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(title, { timeout: 20_000 });
    await expect(page.getByText("Ha dormido bien y ha comido de todo.")).toBeVisible();

    // Agent home: today's entry exists, so no daily nudge and no link card.
    await page.goto("/es/dashboard");
    const rail = suggestionRail(page);
    await expect(rail.getByText(CARD_ALL_DONE, { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(rail.getByText(CARD_TODAY, { exact: true })).toHaveCount(0);
    await expect(rail.getByText(CARD_LINK, { exact: true })).toHaveCount(0);
  });
});
