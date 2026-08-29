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

// Phone shell (390x844, mobile emulation): the header is icon-only ("Subir"
// needs its accessible name, 44px box), the language pill lives in Settings,
// and the tab bar is the navigation. Same rule as above: serious/critical fail.
test("a11y: phone shell", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(
    `e2e-a11y-phone-${Date.now()}@adelia.test`,
  );
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  await context.addCookies([cookie]);
  const page = await context.newPage();

  for (const [path, label] of [
    ["/es/dashboard", "phone/dashboard"],
    ["/es/dashboard/overview", "phone/overview"],
    ["/es/dashboard/settings", "phone/settings"],
    ["/es/dashboard/consulta/grabar", "phone/consulta/grabar"],
  ] as const) {
    await page.goto(path);
    await scan(page, label);
  }
  // 44px touch targets on the phone shell: the icon-only "Subir" (named),
  // the wordmark, the language pill in Settings, the data export link and
  // the "Cerrar" of the install guide.
  async function atLeast44(locator: import("@playwright/test").Locator, what: string) {
    await expect(locator, what).toBeVisible();
    const box = await locator.boundingBox();
    expect(box, what).not.toBeNull();
    expect(box!.width, `${what}: width`).toBeGreaterThanOrEqual(44);
    expect(box!.height, `${what}: height`).toBeGreaterThanOrEqual(44);
  }
  const banner = page.getByRole("banner");
  await atLeast44(banner.getByRole("link", { name: "Subir archivo" }), "Subir");
  await atLeast44(banner.getByRole("link", { name: /Adel\s*IA/ }), "wordmark");
  await page.goto("/es/dashboard/settings");
  for (const button of await page.getByRole("group", { name: "Idioma" }).getByRole("button").all()) {
    await atLeast44(button, "language button");
  }
  await atLeast44(page.getByRole("link", { name: "Descargar todos mis datos" }), "export link");
  // Headless Chromium offers no native install prompt, so Settings shows the
  // guide entry; guard it anyway in case a browser does fire beforeinstallprompt.
  const guideCta = page.getByRole("button", { name: "Ver cómo instalarla" });
  if (await guideCta.isVisible()) {
    await guideCta.click();
    await atLeast44(page.getByRole("dialog").getByRole("button", { name: "Cerrar" }), "guide close");
  }
  await context.close();
});
