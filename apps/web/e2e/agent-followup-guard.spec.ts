import { expect, test, type Browser, type Page } from "@playwright/test";

import es from "../messages/es.json";
import { seedUserAndSessionCookie } from "./utils/session";

// The conversation battery (2026-11-10) found that after the referral for a
// fever at 2 months, «le doy apiretal mientras» was answered as if the
// referral had never been said, and that an adult's question went to the
// agent's tool loop. Both fixes are code, before any model: this runs them
// through the real panel and the real API, nothing mocked, no model key.
test.use({ viewport: { width: 390, height: 844 } });

const OPENING = "Esto no puede esperar a una respuesta mía.";
const REDIRECT =
  "Solo puedo ayudarte con tu bebé, de 0 a 24 meses; si es sobre tu salud, pregúntale a tu médico.";

async function open(browser: Browser, tag: string): Promise<Page> {
  const { cookie } = await seedUserAndSessionCookie(`e2e-agent-guard-${tag}-${Date.now()}@adelia.test`);
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await context.addCookies([cookie]);
  const page = await context.newPage();
  await page.goto("/es/dashboard");
  return page;
}

async function say(page: Page, text: string) {
  // The empty panel's field, or the same field once the conversation started.
  const box = page.getByPlaceholder(es.agent.placeholder)
    .or(page.getByRole("textbox", { name: es.agent.inputLabel })).filter({ visible: true });
  await box.fill(text);
  await box.press("Enter");
}

test("es: after a referral for fever at 2 months, her follow-up gets the referral again", async ({ browser }) => {
  const page = await open(browser, "flag");
  const turns: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/agent/turn") && r.method() === "POST") turns.push(r.postData() ?? "");
  });
  await say(page, "mi bebé de 2 meses tiene 38,2 y no para de llorar");
  const referrals = page.getByText(OPENING, { exact: false }).filter({ visible: true });
  await expect(referrals).toHaveCount(1, { timeout: 20_000 });
  await say(page, "le doy apiretal mientras");
  await expect(referrals).toHaveCount(2, { timeout: 20_000 });
  // The second request carried the referral in its history: the thread read it there.
  expect(turns).toHaveLength(2);
  expect(JSON.parse(turns[1]).history.some((m: { content: string }) => m.content.startsWith(OPENING)))
    .toBe(true);
  await page.screenshot({ path: "test-results/agent-followup-guard-es.png", fullPage: false });
});

test("es: a question about the mother's own health gets the one-sentence redirect", async ({ browser }) => {
  const page = await open(browser, "adult");
  await say(page, "yo tengo dolor de espalda desde el parto que puedo tomar");
  await expect(page.getByText(REDIRECT).filter({ visible: true })).toHaveCount(1, { timeout: 20_000 });
  await page.screenshot({ path: "test-results/agent-redirect-es.png", fullPage: false });
});
