import { expect, test } from "@playwright/test";
import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";

// Same card-free trial as auth.local_trial_end; checkout is an explicit later choice.
for (const [locale, messages, noCard, choice] of [
  ["es", es, /sin tarjeta/i, /decides suscribirte/i],
  ["en", en, /without a card/i, /choose to subscribe/i],
  ["fr", fr, /sans carte/i, /choisis de t’abonner/i],
] as const) {
  test(`${locale}: terms distinguish starting the free trial from choosing a subscription`, async ({ page }) => {
    expect(messages.terms.trialBody).toMatch(noCard);
    expect(messages.terms.trialBody).toMatch(choice);
    await page.goto(`/${locale}/terminos`);
    await expect(page.getByText(messages.terms.trialBody, { exact: true })).toBeVisible();
  });
}
