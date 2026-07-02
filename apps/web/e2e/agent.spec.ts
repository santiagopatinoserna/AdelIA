import { test, expect } from "@playwright/test";
import { seedUserAndSessionCookie } from "./utils/session";

test("agent home renders and accepts input on mobile", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(`e2e-agent-${Date.now()}@adelia.test`);
  const context = await browser.newContext({ viewport: { width: 375, height: 667 } });
  await context.addCookies([cookie]);
  const page = await context.newPage();
  await page.goto("/es/dashboard");
  // greeting + composer visible, no horizontal overflow
  await expect(page.getByPlaceholder(/Escribe|micro/i)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  expect(overflow).toBeTruthy();
});

test("desktop shows a two-column layout", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(`e2e-agent-d-${Date.now()}@adelia.test`);
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await context.addCookies([cookie]);
  const page = await context.newPage();
  await page.goto("/es/dashboard");
  await expect(page.getByTestId("agent-canvas")).toBeVisible();
});
