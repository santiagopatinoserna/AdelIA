import { expect, test } from "@playwright/test";

import { seedUserAndSessionCookie } from "./utils/session";

// iPhone SE — the tightest common viewport. Patient-facing flows must work.
test.use({ viewport: { width: 375, height: 667 } });

test("mobile: dashboard fits and core nav is reachable", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(`e2e-m-${Date.now()}@adelia.test`);
  const context = await browser.newContext({ viewport: { width: 375, height: 667 } });
  await context.addCookies([cookie]);
  const page = await context.newPage();

  await page.goto("/es/dashboard");
  await expect(page.getByRole("heading", { name: "Mis documentos" })).toBeVisible();

  // No horizontal overflow — the page must not scroll sideways on a phone.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
  expect(overflow, "page overflows horizontally on 375px").toBeFalsy();

  // Chat is reachable and usable from the phone.
  await page.getByRole("link", { name: /Chat/ }).first().click();
  await expect(page).toHaveURL(/\/dashboard\/chat/);
});

test("mobile: chat sidebar is a drawer, not a fixed column", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(`e2e-m2-${Date.now()}@adelia.test`);
  const context = await browser.newContext({ viewport: { width: 375, height: 667 } });
  await context.addCookies([cookie]);
  const page = await context.newPage();

  await page.goto("/es/dashboard/chat");

  // The conversation input must be visible — the sidebar must NOT eat the width.
  const input = page.getByPlaceholder(/Pregunta a tu historial/);
  await expect(input).toBeVisible();
  const box = await input.boundingBox();
  expect(box, "chat input not rendered").not.toBeNull();
  // On a 375px screen the input should span most of the width (a fixed 256px
  // sidebar would squeeze it to ~100px).
  expect(box!.width).toBeGreaterThan(250);

  // The drawer toggle exists and opens the sessions panel.
  const toggle = page.getByRole("button", { name: "Ver conversaciones" });
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.getByRole("button", { name: /Nueva conversación/ })).toBeVisible();

  // No horizontal overflow.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
  expect(overflow, "chat overflows horizontally on 375px").toBeFalsy();
});

test("mobile: upload screen is usable", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(`e2e-m3-${Date.now()}@adelia.test`);
  const context = await browser.newContext({ viewport: { width: 375, height: 667 } });
  await context.addCookies([cookie]);
  const page = await context.newPage();

  await page.goto("/es/dashboard/upload");
  await expect(page.getByRole("heading", { name: "Subir documento" })).toBeVisible();
  await expect(page.locator('input[type="file"]')).toBeAttached();
});
