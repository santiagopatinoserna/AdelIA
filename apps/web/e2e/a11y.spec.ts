import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";

// Serious/critical violations fail; minor/moderate get logged for later.
async function scan(page: import("@playwright/test").Page, label: string) {
  // Audit the SETTLED UI: wait for entrance animations (ad-rise fade/slide) to
  // finish so contrast is measured at final opacity, not mid-fade. Capped so a
  // looping animation can never hang the scan.
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
  for (const v of results.violations) {
    console.log(
      `[a11y:${label}] ${v.impact} ${v.id}: ${v.help} (${v.nodes.length} nodes)`,
    );
  }
  expect(blocking, `${label}: ${blocking.map((v) => v.id).join(", ")}`).toEqual([]);
}

test("a11y: public pages", async ({ page }) => {
  await page.goto("/es");
  await scan(page, "home");
  await page.goto("/es/signin");
  await scan(page, "signin");
  await page.goto("/es/profesionales");
  await scan(page, "profesionales");
});

test("a11y: authenticated surfaces", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(
    `e2e-a11y-${Date.now()}@adelia.test`,
  );
  const context = await browser.newContext();
  await context.addCookies([cookie]);
  const page = await context.newPage();

  for (const [path, label] of [
    ["/es/dashboard", "dashboard"],
    ["/es/dashboard/settings", "settings"],
    ["/es/dashboard/chat", "chat"],
    ["/es/dashboard/briefings", "briefings"],
    ["/es/dashboard/briefings/new", "briefings/new"],
    ["/es/dashboard/questionnaire", "questionnaire"],
    ["/es/dashboard/consulta", "consulta"],
    ["/es/dashboard/ingestion", "ingestion"],
    ["/es/dashboard/ingestion/apple-health", "ingestion/apple-health"],
    ["/es/dashboard/ingestion/ccd", "ingestion/ccd"],
    ["/es/dashboard/enrichment", "enrichment"],
    ["/es/dashboard/enrichment/labs", "enrichment/labs"],
    ["/es/dashboard/enrichment/drugs", "enrichment/drugs"],
    ["/es/dashboard/enrichment/profiles", "enrichment/profiles"],
    ["/es/dashboard/enrichment/trials", "enrichment/trials"],
    ["/es/dashboard/enrichment/genomics", "enrichment/genomics"],
    ["/es/dashboard/enrichment/codes", "enrichment/codes"],
    ["/es/dashboard/upload", "upload"],
    ["/es/dashboard/consulta/grabar", "consulta/grabar"],
  ] as const) {
    await page.goto(path);
    await scan(page, label);
  }
  await context.close();
});
