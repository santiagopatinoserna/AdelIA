import { expect, test } from "@playwright/test";

import en from "../messages/en.json";
import es from "../messages/es.json";
import fr from "../messages/fr.json";
import { armModelGuard, note, pageErrors, shot } from "./browser";

// Check 1: the landing in each language loads clean, says what asking keeps
// with a link to Privacy, offers the appointment recorder, and asks nothing
// of the model just by being opened.

const RUN_DIR = process.env.PROD_SMOKE_RUN_DIR!;
const CATALOGS = { es, en, fr } as const;

for (const locale of ["es", "en", "fr"] as const) {
  const g = CATALOGS[locale].guestSpace;

  test(`1.${locale} Portada (${locale})`, async ({ page, context }) => {
    const guard = await armModelGuard(context);
    const errors = pageErrors(page);

    const res = await page.goto(`/${locale}`);
    expect(res?.status(), "landing HTTP status").toBe(200);

    const note_ = page.getByTestId("landing-consent");
    await expect(note_).toBeVisible();
    await expect(note_).toContainText(g.landingNote);
    const privacy = note_.getByRole("link", { name: g.landingPrivacyLink });
    await expect(privacy).toHaveAttribute("href", new RegExp(`^/${locale}/privacidad#sin-cuenta$`));

    const record = page.getByTestId("landing-record");
    await expect(record).toBeVisible();
    await expect(record).toHaveText(g.landingRecord);
    await expect(record).toBeEnabled();

    // Room for the effects of hydration to fire whatever they would fire.
    await page.waitForLoadState("load");
    await page.waitForTimeout(1500);
    await shot(page, RUN_DIR, `01-landing-${locale}`);

    expect(errors, "uncaught page errors").toEqual([]);
    expect(guard.modelRequests, "requests to an answering endpoint on load").toEqual([]);
    note(`landing ${locale}: consent + privacy link + recorder, no page errors, no model request`);
  });
}
