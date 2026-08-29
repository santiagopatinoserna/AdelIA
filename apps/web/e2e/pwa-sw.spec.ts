import { expect, test } from "@playwright/test";

// Service worker (public/sw.js + components/sw-register.tsx) against a
// production build; the worker is not registered under `next dev`.
//  1. it registers as /sw.js?v=<build id> and its cache carries that id,
//  2. a navigation without network gets offline.html, in the URL's locale,
//  3. a worker for another build (what a deploy produces) is announced by the
//     "new version" notice and takes over only after "Actualizar".
test("pwa: service worker registers, serves offline.html without network, announces a new build", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();
  await page.goto("/es");
  await page.waitForFunction(() => !!navigator.serviceWorker?.controller, null, { timeout: 30_000 });

  const controller = await page.evaluate(() => navigator.serviceWorker.controller!.scriptURL);
  const version = new URL(controller).searchParams.get("v");
  expect(version, controller).toBeTruthy();
  expect(version).not.toBe("dev");
  await expect
    .poll(() => page.evaluate(() => caches.keys()), { timeout: 15_000 })
    .toContain(`adelia-${version}`);
  expect(await page.evaluate(() => caches.match("/offline.html").then((r) => !!r))).toBe(true);

  // 2. No network, French URL: the fallback speaks French.
  await context.setOffline(true);
  await page.goto("/fr/dashboard");
  await expect(page.getByRole("heading", { name: "Hors ligne" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sin conexión" })).toBeHidden();
  await context.setOffline(false);

  await page.goto("/es");
  await page.waitForFunction(() => !!navigator.serviceWorker?.controller, null, { timeout: 30_000 });
  await expect(page.getByTestId("app-update")).toHaveCount(0);

  // 3. A deploy: a worker for another build id installs and waits.
  await page.evaluate(() => navigator.serviceWorker.register("/sw.js?v=e2e-next"));
  const notice = page.getByTestId("app-update");
  await expect(notice).toBeVisible({ timeout: 30_000 });
  await expect(notice).toContainText("Hay una versión nueva");
  // Waiting, not controlling: nothing reloaded under the user.
  expect(await page.evaluate(() => navigator.serviceWorker.controller!.scriptURL)).toBe(controller);

  await Promise.all([
    page.waitForEvent("load"),
    notice.getByRole("button", { name: "Actualizar" }).click(),
  ]);
  const navType = await page.evaluate(
    () => (performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming).type,
  );
  expect(navType).toBe("reload");

  // The reloaded page registers its own build again; since the page already
  // runs that build it activates silently (no notice, no second reload) and
  // the e2e-next cache is purged on activation.
  await expect
    .poll(() => page.evaluate(() => caches.keys()), { timeout: 15_000 })
    .not.toContain("adelia-e2e-next");
  expect(await page.evaluate(() => caches.keys())).toContain(`adelia-${version}`);
  await expect(page.getByTestId("app-update")).toHaveCount(0);
  await context.close();
});
