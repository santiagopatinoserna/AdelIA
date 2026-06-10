import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";

// Serious/critical violations fail; minor/moderate get logged for later.
async function scan(page: import("@playwright/test").Page, label: string) {
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
    ["/es/dashboard/briefings", "briefings"],
    ["/es/dashboard/ingestion", "ingestion"],
    ["/es/dashboard/enrichment", "enrichment"],
    ["/es/dashboard/upload", "upload"],
  ] as const) {
    await page.goto(path);
    await scan(page, label);
  }
  await context.close();
});
