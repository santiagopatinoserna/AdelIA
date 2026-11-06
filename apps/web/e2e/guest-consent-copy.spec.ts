import { expect, test } from "@playwright/test";

import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";

// Review of PR #57 (2026-11-06). The guest's privacy text said "nobody else sees
// it", which is false: the same processors as for an account handle it, and the
// privacy page names them. It now says so and links to that part of the page
// instead of repeating it. Lucía is the baby the guest space starts with, never
// "made up" or "fictional" (Santiago), and never the visitor's own child. Next
// to "Preguntar" the landing says, in one line, that asking means agreeing to
// keep what she does in her space, with a link to Privacy and where to delete
// it. A draft for Santiago's review.

const catalogs = { es, en, fr } as const;
const LOCALES = ["es", "en", "fr"] as const;

const FALSE_CLAIM = /nadie más lo ve|nobody else sees|personne d’autre ne le voit/i;
const MADE_UP = /inventad|ficti|invent|made[- ]up|fictive/i;
const PROCESSOR_NAMES = /Anthropic|Mistral|Cloudflare/;
const OWN_CHILD = /tu hija|tu bebé|your daughter|your baby|ta fille|ton bébé/i;

for (const locale of LOCALES) {
  const g = catalogs[locale].guestSpace as Record<string, string>;

  test(`guest privacy text points to the processors without the false claim (${locale})`, () => {
    expect(g.privacyBody).not.toMatch(FALSE_CLAIM);
    expect(g.privacyBody).not.toMatch(MADE_UP);
    expect(g.privacyBody).not.toMatch(OWN_CHILD);
    expect(g.privacyBody).not.toMatch(PROCESSOR_NAMES);
    expect(g.privacyBody).toMatch(/<processors>[^<]+<\/processors>/);
    expect(g.privacyBody).toContain("Lucía");
  });

  test(`the landing note asks for consent in one line (${locale})`, () => {
    expect(g.landingNote).not.toMatch(MADE_UP);
    expect(g.landingNote).not.toMatch(/\n/);
    expect(g.landingPrivacyLink.length).toBeGreaterThan(0);
  });

  test(`live: the guest section links to the processors on the privacy page (${locale})`, async ({
    page,
  }) => {
    await page.goto(`/${locale}/privacidad`);
    const guest = page.getByTestId("privacy-guest");
    await expect(guest).not.toContainText(FALSE_CLAIM);
    const link = guest.locator('a[href$="#encargados"]');
    await expect(link).toHaveCount(1);
    await expect(page.locator("#encargados")).toContainText("Anthropic");
    await expect(page.locator("#encargados")).toContainText("Mistral");
    await expect(page.locator("#encargados")).toContainText("Cloudflare");
  });

  test(`live: next to "Preguntar" the landing says asking keeps her space (${locale})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/${locale}`);
    const ask = page.getByTestId("demo-ask");
    const note = ask.getByTestId("landing-consent");
    await expect(note).toBeVisible();
    await expect(note).toContainText(g.landingNote);
    const privacy = note.getByRole("link", { name: g.landingPrivacyLink });
    await expect(privacy).toHaveAttribute("href", new RegExp(`^/${locale}/privacidad#sin-cuenta$`));
    // Right under the button, before anything else the form holds.
    const button = ask.locator('button[type="submit"]');
    const [b, n] = [await button.boundingBox(), await note.boundingBox()];
    expect(n!.y).toBeGreaterThan(b!.y);
    expect(n!.y - (b!.y + b!.height)).toBeLessThan(40);
  });
}
