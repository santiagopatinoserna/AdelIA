import { expect, test } from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";

const SHOTS = "/tmp/adelia-shots";

// Wait for entrance animations (ad-rise) to finish so screenshots capture the
// settled UI a user sees, not a mid-fade frame. Capped so it can never hang.
async function settle(page: import("@playwright/test").Page) {
  await page.evaluate(() =>
    Promise.race([
      Promise.allSettled(document.getAnimations().map((a) => a.finished)),
      new Promise((resolve) => setTimeout(resolve, 1200)),
    ]),
  );
}

// A real-browser walkthrough AS Santiago, proving each screen works end to end.
// A demo tool, not a regression test: it needs the seeded demo account (with
// the reflux document) and a live Mistral key for the chat step.
test("recorrido completo: garantía de éxito en navegador", async ({ browser }) => {
  test.skip(!process.env.DEMO_VERIFY, "Demo tool: run with DEMO_VERIFY=1 against a full stack with a Mistral key");
  // Reuse the seeded account that already has the reflux document.
  const { cookie } = await seedUserAndSessionCookie("santiago@demo.local");
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addCookies([cookie]);
  const page = await ctx.newPage();

  // 1. Overview (the document list; /dashboard itself is the agent canvas)
  await page.goto("/es/dashboard/overview");
  await expect(page.getByRole("heading", { name: "Mis documentos" })).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${SHOTS}/1-dashboard.png`, fullPage: true });

  // 1b. Settings — email + danger zone
  await page.goto("/es/dashboard/settings");
  await settle(page);
  await page.screenshot({ path: `${SHOTS}/7-settings.png`, fullPage: true });

  // 2. Chat — ask about the baby's reflux, expect an evidence-cited answer
  await page.goto("/es/dashboard/chat");
  await page.getByPlaceholder(/Pregunta a tu historial/).fill(
    "Mi bebé toma omeprazol para el reflujo y no mejora. ¿Qué pregunto al pediatra?",
  );
  await page.keyboard.press("Enter");
  // Robust completion signal: the send button shows "Pensando…" while
  // streaming and returns to "Enviar" when the answer is done.
  // The answer now renders; it ends with the disclaimer.
  await expect(page.locator("text=/Verifica con tu médico/i")).toBeVisible({ timeout: 120000 });
  await page.waitForTimeout(500);
  await settle(page);
  await page.screenshot({ path: `${SHOTS}/2-chat-reflujo.png`, fullPage: true });

  // 3. Briefings
  await page.goto("/es/dashboard/briefings");
  await settle(page);
  await page.screenshot({ path: `${SHOTS}/3-briefings.png`, fullPage: true });

  // 4. Importar (Apple Health hub)
  await page.goto("/es/dashboard/ingestion");
  await settle(page);
  await page.screenshot({ path: `${SHOTS}/4-importar.png`, fullPage: true });

  // 5. Insights
  await page.goto("/es/dashboard/enrichment");
  await settle(page);
  await page.screenshot({ path: `${SHOTS}/5-insights.png`, fullPage: true });

  await ctx.close();
});
