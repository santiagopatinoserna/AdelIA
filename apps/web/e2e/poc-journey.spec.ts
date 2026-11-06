import { expect, test, type Locator, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { Pool } from "pg";

import es from "../messages/es.json";
import fr from "../messages/fr.json";
import { isoMonthsAgo } from "./utils/seed";
import { magicLinkPath } from "./utils/session";

// The whole road of a new mother with an account, on a phone, in Spanish and
// in French, against the real API WITHOUT a model key (docs/design/RECORRIDO_POC.md):
// sign up with a card-free trial, the three baby questions, the home, a first
// question to the agent and to the chat, a diary line confirmed and read back
// in "Hoy con <nombre>", a PDF upload, the history, the specialist report and
// its share link, settings, export, sign out and back in, delete.
//
// Real everywhere a key is not needed: the magic link is the one the email
// would carry (the inbox is the only thing skipped), the diary line is read by
// the rules in agent/record.py, the deterministic paths answer. Only the agent
// answer after "ask again" is mocked, because answering needs a model, and the
// report to share is seeded, because writing one needs a model too.

test.use({ viewport: { width: 390, height: 844 }, acceptDownloads: true });
test.setTimeout(240_000);

const PDF = path.resolve(__dirname, "../../api/tests/fixtures/sample-lab-result.pdf");
const API = process.env.E2E_API_URL ?? "http://localhost:8000";

function pgPool() {
  return new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? "5434"),
    user: process.env.POSTGRES_USER ?? "adelia",
    password: process.env.POSTGRES_PASSWORD ?? "adelia_dev",
    database: process.env.POSTGRES_DB ?? "adelia",
  });
}

async function query<T = Record<string, unknown>>(sql: string, args: unknown[]): Promise<T[]> {
  const db = pgPool();
  try {
    return (await db.query(sql, args)).rows as T[];
  } finally {
    await db.end();
  }
}

const LOCALES = [
  {
    locale: "es", m: es, baby: "Lucía",
    question: "Regurgita después de cada toma, ¿es normal?",
    diary: "hoy ha tenido 37,8 a las 5",
    noted: /Anotado:\s37,8\s°C/,
  },
  {
    locale: "fr", m: fr, baby: "Lucie",
    question: "Elle régurgite après chaque tétée, c’est normal ?",
    diary: "aujourd'hui elle a eu 37,8 à 5 heures",
    noted: /C’est noté\s:\s37,8\s°C/,
  },
] as const;

// A run that fails halfway leaves its account behind in a shared database; a
// green run has already deleted it through the UI (step 15).
const createdEmails: string[] = [];
test.afterAll(async () => {
  if (createdEmails.length === 0) return;
  await query("DELETE FROM users WHERE email = ANY($1::text[])", [createdEmails]);
});

const sse = (events: [string, unknown][]) =>
  events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");

// React attaches its props to a DOM node when it hydrates it; before that a
// file chosen, a box ticked or a button pressed goes nowhere and leaves no
// error. CI under load can hand the test a page that has loaded but not yet
// hydrated: the upload never left (stored/refused both false for 30 s) and the
// delete button never armed (no navigation in 20 s). Wait for the handlers.
async function hydrated(locator: Locator) {
  await locator.waitFor({ state: "attached" });
  await expect
    .poll(() => locator.evaluate((el) => Object.keys(el).some((k) => k.startsWith("__reactProps$"))))
    .toBe(true);
}

async function ask(page: Page, placeholder: string, text: string) {
  const box = page.getByPlaceholder(placeholder);
  await box.fill(text);
  await box.press("Enter");
}

test("the sign-in form never says the link left when it did not", async ({ page }) => {
  // A real Resend key would send a real email to a .test inbox.
  test.skip(!!process.env.RESEND_API_KEY, "only meaningful when the email cannot be sent");
  // Without a working mail provider the email never leaves. It used to show
  // "Revisa tu correo" anyway, and she waited for a link that would never come.
  await page.goto("/es/signin");
  await page.locator("#email").fill(`e2e-poc-nomail-${Date.now()}@adelia.test`);
  await page.getByRole("button", { name: es.signin.sendMagicLink }).click();
  await expect(page.getByText(es.signin.errorMsg)).toBeVisible();
  await expect(page.getByText(es.signin.sentTitle)).toHaveCount(0);
});

for (const L of LOCALES) {
  test(`${L.locale}: a new mother walks the whole road without a model key`, async ({ page }) => {
    const { m } = L;
    const crashes: string[] = [];
    page.on("pageerror", (e) => crashes.push(e.message));
    const email = `e2e-poc-${L.locale}-${Date.now()}@adelia.test`;
    createdEmails.push(email);

    // 1. Sign up: the magic link creates the account with a card-free trial.
    await page.goto(await magicLinkPath(email, `/${L.locale}/dashboard`));
    await expect(page).toHaveURL(new RegExp(`/${L.locale}/onboarding$`));
    const [user] = await query<{ id: string; subscription_status: string | null }>(
      "SELECT id, subscription_status FROM users WHERE email = $1", [email]);
    expect(user.subscription_status ?? "none").toBe("none");

    // 2. Onboarding: three questions about the baby.
    await page.getByLabel(m.onboarding.nameLabel).fill(L.baby);
    await page.getByLabel(m.onboarding.dobLabel).fill(isoMonthsAgo(4));
    await page.getByLabel(m.onboarding.sexLabel).selectOption("F");
    await page.getByRole("button", { name: m.onboarding.submit }).click();
    await page.waitForURL(new RegExp(`/${L.locale}/dashboard$`), { timeout: 30_000 });

    // 3. Home: her baby first, and no "Mi perfil" chip beside a baby she
    //    just named (the auto-created self row, in Spanish even in French).
    await expect(page.getByRole("heading", { level: 1 }))
      .toHaveText(m.agent.greetingWithName.replace("{name}", L.baby));
    await expect(page.getByRole("button", { name: "Mi perfil" })).toHaveCount(0);
    await expect(page.getByTestId("today-card")).toBeVisible();

    // 4. First question to the agent. No key: an honest sentence and a way to
    //    ask again, not "check your connection" and not a dead end.
    await ask(page, m.agent.placeholder, L.question);
    await expect(page.getByText(m.agent.unavailableAnswer)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(m.agent.errorAnswer)).toHaveCount(0);
    // When the model is back, "ask again" sends the same words once.
    const bodies: { message?: string }[] = [];
    await page.route("**/api/backend/agent/turn", (route) => {
      bodies.push(JSON.parse(route.request().postData() ?? "{}"));
      return route.fulfill({
        status: 200, contentType: "text/event-stream",
        body: sse([["start", {}], ["token", { content: "Respuesta simulada del modelo." }],
                   ["final", { citations: [], evidence_citations: [] }]]),
      });
    });
    await page.getByRole("button", { name: m.agent.retry }).click();
    await expect(page.getByText("Respuesta simulada del modelo.")).toBeVisible();
    expect(bodies.map((b) => b.message)).toEqual([L.question]);
    await expect(page.locator('[data-role="user"]')).toHaveCount(1);
    await expect(page.getByText(m.agent.unavailableAnswer)).toHaveCount(0);
    await page.unroute("**/api/backend/agent/turn");

    // 5. The same question in the chat, real API, no key.
    await page.goto(`/${L.locale}/dashboard/chat`);
    await ask(page, m.chat.placeholder, L.question);
    await expect(page.getByText(m.chat.unavailableAnswer)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(m.chat.errorAnswer)).toHaveCount(0);
    await expect(page.getByRole("button", { name: m.chat.retry })).toBeVisible();

    // 6. A diary line, read by rules (no model), confirmed with one tap.
    await page.goto(`/${L.locale}/dashboard`);
    await ask(page, m.agent.placeholder, L.diary);
    const card = page.locator('[data-testid="confirm-card"]:visible');
    await expect(card.getByTestId("confirm-body")).toContainText("37,8 °C", { timeout: 30_000 });
    await card.getByRole("button", { name: m.agent.confirmYes, exact: true }).click();
    await expect(page.getByText(L.noted)).toBeVisible({ timeout: 30_000 });

    // 7. "Hoy con <nombre>" reads it back. "a las 5" is today at 17:00, or
    //    yesterday's 17:00 before five in the morning; the card shows both.
    await page.goto(`/${L.locale}/dashboard`);
    const today = page.getByTestId("today-card");
    await expect(today.getByRole("heading"))
      .toHaveText(m.today.titleWithName.replace("{name}", L.baby));
    await expect(today).toContainText("37,8");

    // 8. A PDF report. Without a key it cannot be read, and the history says
    //    so next to a name she can still recognise.
    await page.goto(`/${L.locale}/dashboard/upload`);
    await hydrated(page.locator('input[type="file"]'));
    await page.locator('input[type="file"]').setInputFiles(PDF);
    const stored = async () =>
      (await query("SELECT 1 FROM documents WHERE user_id = $1", [user.id])).length === 1;
    const refused = page.getByText(m.upload.errGeneric);
    await expect.poll(async () => (await stored()) || (await refused.isVisible()), {
      timeout: 30_000,
    }).toBe(true);
    if (!(await stored())) {
      // CI's e2e job runs no object storage, so the API cannot keep the file.
      // Seed the row it would have written, already failed to read (no key):
      // processed, no text. Locally, with MinIO, the real upload is walked.
      test.info().annotations.push({ type: "seeded", description: "upload: no object storage" });
      await query(
        `INSERT INTO documents (id, user_id, profile_id, source, mime_type, s3_key, processed_at)
         SELECT gen_random_uuid(), $1, p.id, 'web', 'application/pdf', $2, now()
           FROM profiles p WHERE p.user_id = $1 AND p.relationship = 'child'`,
        [user.id, `users/${user.id}/${crypto.randomUUID()}-sample-lab-result.pdf`]);
    }

    // 9. History: the file is there, its name readable at 390 px.
    await page.goto(`/${L.locale}/dashboard/overview`);
    const name = page.getByText("sample-lab-result.pdf", { exact: true });
    await expect(name).toBeVisible();
    expect(await name.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);

    // 10. The report for the specialist: generating needs a model, so it
    //     fails, and says so with a way forward instead of spinning forever.
    await page.goto(`/${L.locale}/dashboard/briefings/new`);
    await page.getByRole("button", { name: m.briefing.createButton }).click();
    await expect(page.getByText(m.briefing.failure.title)).toBeVisible({ timeout: 90_000 });

    // 11. Share: a ready report (seeded: writing one needs a model) gets a
    //     link that opens without an account.
    const [profile] = await query<{ id: string }>(
      "SELECT id FROM profiles WHERE user_id = $1 AND relationship = 'child'", [user.id]);
    const [ready] = await query<{ id: string }>(
      `INSERT INTO briefings (user_id, profile_id, target_specialty, status, html_render, completed_at, payload)
       VALUES ($1, $2, 'pediatrics', 'ready', $3, now(), '{}'::jsonb) RETURNING id`,
      [user.id, profile.id, `<h1>Informe e2e de ${L.baby}</h1>`]);
    await page.goto(`/${L.locale}/dashboard/briefings/${ready.id}`);
    await page.getByRole("button", { name: m.briefing.share.button }).click();
    await page.getByLabel(m.briefing.share.privacyAck).check();
    await page.getByRole("button", { name: m.briefing.share.createButton }).click();
    const shareUrl = (await page.locator("code").filter({ hasText: "/s/" }).innerText()).trim();
    const token = shareUrl.split("/s/")[1];
    const pub = await page.request.get(`${API}/s/${token}`, { headers: { cookie: "" } });
    expect(pub.status()).toBe(200);
    expect(await pub.text()).toContain(`Informe e2e de ${L.baby}`);
    await page.keyboard.press("Escape");

    // 12. Settings and export: her baby and her note are in the file.
    await page.goto(`/${L.locale}/dashboard/settings`);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: m.settings.exportCta }).click(),
    ]);
    const exported = readFileSync(await download.path(), "utf8");
    expect(exported).toContain(L.baby);
    expect(JSON.parse(exported).adelia.observations).toHaveLength(1);

    // 13. Sign out from settings, and the panel is closed behind her.
    await hydrated(page.getByRole("button", { name: m.settings.signOutCta }));
    await page.getByRole("button", { name: m.settings.signOutCta }).click();
    await page.waitForURL((u) => !u.pathname.includes("/dashboard"), { timeout: 20_000 });
    await page.goto(`/${L.locale}/dashboard`);
    await expect(page).toHaveURL(new RegExp(`/${L.locale}/signin`));

    // 14. Back in with a new link: straight to her baby, no second onboarding.
    await page.goto(await magicLinkPath(email, `/${L.locale}/dashboard`));
    await expect(page).toHaveURL(new RegExp(`/${L.locale}/dashboard$`));
    await expect(page.getByRole("heading", { level: 1 }))
      .toHaveText(m.agent.greetingWithName.replace("{name}", L.baby));

    // 15. Delete the account: nothing of hers is left.
    await page.goto(`/${L.locale}/dashboard/settings`);
    await hydrated(page.getByLabel(m.settings.ackIrreversible));
    await page.getByLabel(m.settings.ackIrreversible).check();
    await page.locator("#confirm-delete").fill(email);
    // Armed only once both safeguards reached React state; a press before that
    // does nothing and the test would wait 20 s for a navigation that never comes.
    await expect(page.getByRole("button", { name: m.settings.deleteButton })).toBeEnabled();
    // A bare "Timeout" here said nothing for three CI failures. The cause was
    // a DELETE that answered 204 after 21.6 s (routers/users.py swept every
    // blob in the system before answering). Say which step stalled and why.
    const sent = Date.now();
    const erased = page.waitForResponse(
      (r) => r.url().endsWith("/api/backend/users/me") && r.request().method() === "DELETE",
      { timeout: 20_000 },
    ).catch(() => null);
    await page.getByRole("button", { name: m.settings.deleteButton }).click();
    const res = await erased;
    expect(res, "DELETE /users/me gave no answer within 20 s").not.toBeNull();
    const ms = Date.now() - sent;
    expect(res!.status(), `DELETE /users/me answered ${res!.status()} after ${ms} ms: `
      + `${await res!.text().catch(() => "")}`).toBe(204);
    const left = await page
      .waitForURL((u) => !u.pathname.includes("/dashboard"), { timeout: 20_000 })
      .then(() => true, () => false);
    const shown = await page.getByText(m.settings.actionError).isVisible();
    expect(left, `204 after ${ms} ms but still on ${page.url()}; error shown: ${shown}`)
      .toBe(true);
    expect(await query("SELECT 1 FROM users WHERE email = $1", [email])).toHaveLength(0);

    expect(crashes).toEqual([]);
  });
}
