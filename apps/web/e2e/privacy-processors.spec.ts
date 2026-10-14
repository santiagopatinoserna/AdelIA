import { expect, test } from "@playwright/test";

// Audit 1.12. The privacy policy closed its list of processors with "no data goes
// further than these four" while Cloudflare terminated the TLS of the domain and the
// tunnel crossed its network. The policy now names Cloudflare and counts five. The
// catalogs are also checked by apps/api/tests/test_privacy_policy.py; this test reads
// the page a person actually sees, in the three languages.

const EXPECTED: Record<string, { closing: RegExp; stale: RegExp; role: RegExp }> = {
  es: {
    closing: /Ningún dato va más allá de estos cinco\./,
    stale: /estos cuatro/,
    role: /Cloudflare \(Cloudflare, Inc\., EE\. UU\.\) termina el cifrado TLS de adelia\.godi\.ai/,
  },
  en: {
    closing: /Nothing goes further than these five\./,
    stale: /these four/,
    role: /Cloudflare \(Cloudflare, Inc\., USA\) terminates the TLS encryption for adelia\.godi\.ai/,
  },
  fr: {
    closing: /Aucune donnée ne va plus loin que ces cinq-là\./,
    stale: /ces quatre/,
    role: /Cloudflare \(Cloudflare, Inc\., États-Unis\) termine le chiffrement TLS du domaine adelia\.godi\.ai/,
  },
};

for (const locale of ["es", "en", "fr"]) {
  test(`the privacy page declares Cloudflare and counts five processors (${locale})`, async ({
    page,
  }) => {
    await page.goto(`/${locale}/privacidad`);
    const main = page.getByRole("main");
    await expect(main).toContainText(EXPECTED[locale].role);
    await expect(main).toContainText(EXPECTED[locale].closing);
    await expect(main).not.toContainText(EXPECTED[locale].stale);
  });
}
