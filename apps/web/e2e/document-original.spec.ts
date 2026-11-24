import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser } from "@playwright/test";
import { Pool } from "pg";

import es from "../messages/es.json";
import { isoMonthsAgo, seedProfile } from "./utils/seed";
import { seedUserAndSessionCookie } from "./utils/session";

// The vault promise (docs/specs/ADELIA_SIMPLE.md, 2026-11-24): what she sends
// she can open again, byte for byte, even when reading it failed. Against the
// REAL API and MinIO with no model key: the pipeline cannot read the PDF then,
// which is the case where her original matters most.

const PHONE = { width: 390, height: 844 };
// Every byte value after the header, so a text decode on the way back shows.
const PDF = Buffer.concat([
  Buffer.from("%PDF-1.4\n% analitica de Lucia\n"),
  Buffer.from(Array.from({ length: 256 }, (_, i) => i)),
]);

function pgPool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

async function signedIn(browser: Browser, tag: string) {
  const { cookie, userId } = await seedUserAndSessionCookie(
    `e2e-original-${tag}-${Date.now()}@adelia.test`,
  );
  const profileId = await seedProfile(userId, { displayName: "Lucía", dateOfBirth: isoMonthsAgo(5) });
  const context = await browser.newContext({ viewport: PHONE });
  await context.addCookies([cookie]);
  return { context, page: await context.newPage(), userId, profileId };
}

test("the file she uploaded opens again, byte for byte", async ({ browser }) => {
  const { context, page } = await signedIn(browser, "pdf");

  await page.goto("/es/dashboard/upload");
  const uploaded = page.waitForResponse(
    (r) => r.url().endsWith("/api/backend/documents") && r.request().method() === "POST",
  );
  await page.setInputFiles('input[type="file"]', {
    name: "analítica lucía.pdf",
    mimeType: "application/pdf",
    buffer: PDF,
  });
  const res = await uploaded;
  expect(res.status()).toBe(201);
  const { id } = (await res.json()) as { id: string };

  await page.goto(`/es/dashboard/documents/${id}`);
  const link = page.getByTestId("document-original");
  await expect(link).toHaveText(es.dashboard.docOriginal);
  await expect(link).toHaveAttribute("target", "_blank");

  // Through the same-origin proxy, with her session, as the tab would get it.
  const file = await page.request.get((await link.getAttribute("href")) ?? "");
  expect(file.status()).toBe(200);
  expect(Buffer.compare(await file.body(), PDF)).toBe(0);
  const headers = file.headers();
  expect(headers["content-type"]).toBe("application/pdf");
  expect(headers["content-disposition"]).toMatch(/^inline;/);
  expect(headers["cache-control"]).toBe("private, no-store");
  const utf8Name = headers["content-disposition"].split("filename*=UTF-8''")[1];
  expect(decodeURIComponent(utf8Name)).toBe("analítica_lucía.pdf");

  const audit = await new AxeBuilder({ page }).analyze();
  expect(audit.violations).toEqual([]);
  if (process.env.E2E_SHOTS) {
    await page.screenshot({ path: `${process.env.E2E_SHOTS}/document-original.png` });
  }
  await context.close();
});

test("a consultation keeps its text and offers no audio to download", async ({ browser }) => {
  const { context, page, userId, profileId } = await signedIn(browser, "consulta");
  const key = `users/${userId}/${Date.now()}-consulta.webm`;
  const db = pgPool();
  const { rows } = await db.query(
    `INSERT INTO documents (id, user_id, profile_id, source, mime_type, s3_key, raw_text, processed_at)
     VALUES (gen_random_uuid(), $1, $2, 'consulta', 'audio/webm', $3,
             '[Hablante 1] La vacuna de los seis meses, el martes.', now())
     RETURNING id`,
    [userId, profileId, key],
  );
  // What the upload writes for every consultation (DPIA retention clock).
  await db.query(
    `INSERT INTO blob_tombstones (s3_key, not_before) VALUES ($1, now() + interval '48 hours')`,
    [key],
  );
  await db.end();

  await page.goto(`/es/dashboard/documents/${rows[0].id}`);
  await expect(page.getByText("La vacuna de los seis meses, el martes.")).toBeVisible();
  await expect(page.getByText(es.consulta.record.audioDeleted)).toBeVisible();
  await expect(page.getByTestId("document-original")).toHaveCount(0);
  await context.close();
});

// A failed transcription: the audio is what a retry needs, and the DPIA
// deletes it 7 days later. The page gives the date while it waits, and once
// it is gone it says so instead of offering a retry that cannot work.
test("a failed consultation says until when its audio waits, then that it is gone", async ({
  browser,
}) => {
  const { context, page, userId, profileId } = await signedIn(browser, "failed");
  const db = pgPool();
  const ids: string[] = [];
  for (const kept of [true, false]) {
    const key = `users/${userId}/${Date.now()}-${kept ? "kept" : "gone"}-consulta.webm`;
    const { rows } = await db.query(
      `INSERT INTO documents (id, user_id, profile_id, source, mime_type, s3_key, raw_text, processed_at)
       VALUES (gen_random_uuid(), $1, $2, 'consulta', 'audio/webm', $3, NULL, now())
       RETURNING id`,
      [userId, profileId, key],
    );
    if (kept) {
      await db.query(
        `INSERT INTO blob_tombstones (s3_key, not_before) VALUES ($1, '2030-01-15T10:00:00Z')`,
        [key],
      );
    }
    ids.push(rows[0].id);
  }
  await db.end();

  await page.goto(`/es/dashboard/documents/${ids[0]}`);
  await expect(page.getByText(es.dashboard.docFailedTitle)).toBeVisible();
  await expect(page.getByText(/El audio se guarda hasta el 15 de enero de 2030/)).toBeVisible();
  await expect(page.getByRole("button", { name: es.dashboard.retryDoc })).toBeVisible();
  const audit = await new AxeBuilder({ page }).analyze();
  expect(audit.violations).toEqual([]);
  if (process.env.E2E_SHOTS) {
    await page.screenshot({ path: `${process.env.E2E_SHOTS}/consulta-failed-kept.png` });
  }

  await page.goto(`/es/dashboard/documents/${ids[1]}`);
  await expect(page.getByText(es.dashboard.docFailedAudioGone)).toBeVisible();
  await expect(page.getByRole("button", { name: es.dashboard.retryDoc })).toHaveCount(0);
  await context.close();
});
