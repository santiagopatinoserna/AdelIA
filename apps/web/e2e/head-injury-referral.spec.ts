import { expect, test, type Browser, type Page } from "@playwright/test";

import en from "../messages/en.json";
import es from "../messages/es.json";
import fr from "../messages/fr.json";
import { seedUserAndSessionCookie } from "./utils/session";

// The #retr4 finding (2026-11-11): «se ha dado un golpe en la cabeza y ha
// perdido el conocimiento» and «ha vomitado varias veces» after a knock went
// past the red-flag guard to the model. The guard is code, before any model:
// this runs the mother's words through the real panel and the real API,
// nothing mocked, no model key, and checks she gets the referral, the reason
// in her language and the SEUP sheet as its source.
test.use({ viewport: { width: 390, height: 844 } });

const CATALOGS = { es, en, fr } as const;

const CASES = [
  {
    locale: "es",
    say: "se ha dado un golpe en la cabeza y ha perdido el conocimiento",
    opening: "Esto no puede esperar a una respuesta mía.",
    reason: "señal de alarma tras un golpe en la cabeza",
  },
  {
    locale: "en",
    say: "she bumped her head and has been sick three times",
    opening: "This cannot wait for an answer from me.",
    reason: "warning sign after a knock to the head",
  },
  {
    locale: "fr",
    say: "il est tombé sur la tête et a perdu connaissance",
    opening: "Cela ne peut pas attendre une réponse de ma part.",
    reason: "signe d’alerte après un coup à la tête",
  },
] as const;

const SEUP = "Traumatismo craneal, información para padres (SEUP)";

async function open(browser: Browser, locale: string, tag: string): Promise<Page> {
  const { cookie } = await seedUserAndSessionCookie(
    `e2e-head-injury-${tag}-${Date.now()}@adelia.test`,
  );
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await context.addCookies([cookie]);
  const page = await context.newPage();
  await page.goto(`/${locale}/dashboard`);
  return page;
}

async function say(page: Page, locale: keyof typeof CATALOGS, text: string) {
  const agent = CATALOGS[locale].agent;
  const box = page.getByPlaceholder(agent.placeholder)
    .or(page.getByRole("textbox", { name: agent.inputLabel })).filter({ visible: true });
  await box.fill(text);
  await box.press("Enter");
}

for (const c of CASES) {
  test(`${c.locale}: a knock to the head with an alarm sign gets the referral`, async ({
    browser,
  }) => {
    const page = await open(browser, c.locale, c.locale);
    await say(page, c.locale, c.say);
    await expect(page.getByText(c.opening, { exact: false }).filter({ visible: true }))
      .toHaveCount(1, { timeout: 20_000 });
    await expect(page.getByText(c.reason, { exact: false }).filter({ visible: true }).first())
      .toBeVisible();
    await expect(page.getByText("112", { exact: false }).filter({ visible: true }).first())
      .toBeVisible();
    await expect(page.getByText(SEUP, { exact: false }).first()).toBeAttached();
    await page.screenshot({ path: `test-results/head-injury-${c.locale}.png`, fullPage: true });
  });
}
