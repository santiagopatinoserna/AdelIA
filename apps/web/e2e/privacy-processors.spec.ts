import { expect, test } from "@playwright/test";

// Audit 1.12. The privacy policy closed its list of processors with "no data goes
// further than these four" while Cloudflare terminated the TLS of the domain and the
// tunnel crossed its network. The policy then named Cloudflare and counted five. On
// 2026-11-03 Anthropic joined as the sixth, before LLM_PROVIDER=anthropic sends health
// data to Claude outside the EU, so the page must say so and must not keep the old count.
// On 2026-11-24 GitHub joined as the seventh: it holds the offsite backup, encrypted
// before it leaves the server (docs/BACKUPS.md), and is declared all the same.
// The catalogs are also checked by apps/api/tests/test_privacy_policy.py; this test reads
// the page a person actually sees, in the three languages.

const EXPECTED: Record<
  string,
  { closing: RegExp; stale: RegExp; role: RegExp; anthropic: RegExp; github: RegExp }
> = {
  es: {
    closing: /Ningún dato va más allá de estos siete\./,
    stale: /estos (cuatro|cinco|seis)\./,
    role: /Cloudflare \(Cloudflare, Inc\., EE\. UU\.\) termina el cifrado TLS de adelia\.godi\.ai/,
    anthropic: /Ese procesamiento se hace fuera de la UE/,
    github: /GitHub guarda archivos que no puede leer/,
  },
  en: {
    closing: /Nothing goes further than these seven\./,
    stale: /these (four|five|six)\./,
    role: /Cloudflare \(Cloudflare, Inc\., USA\) terminates the TLS encryption for adelia\.godi\.ai/,
    anthropic: /That processing happens outside the EU/,
    github: /GitHub stores files it cannot read/,
  },
  fr: {
    closing: /Aucune donnée ne va plus loin que ces sept-là\./,
    stale: /ces (quatre|cinq|six)-là/,
    role: /Cloudflare \(Cloudflare, Inc\., États-Unis\) termine le chiffrement TLS du domaine adelia\.godi\.ai/,
    anthropic: /Ce traitement a lieu hors de l’UE/,
    github: /GitHub garde des fichiers qu’il ne peut pas lire/,
  },
};

for (const locale of ["es", "en", "fr"]) {
  test(`the privacy page declares Cloudflare, Anthropic and GitHub and counts seven processors (${locale})`, async ({
    page,
  }) => {
    await page.goto(`/${locale}/privacidad`);
    const main = page.getByRole("main");
    await expect(main).toContainText(EXPECTED[locale].role);
    await expect(main).toContainText(/Anthropic \(Anthropic Ireland, Limited\)/);
    await expect(main).toContainText(EXPECTED[locale].anthropic);
    await expect(main).toContainText(EXPECTED[locale].github);
    await expect(main).toContainText(EXPECTED[locale].closing);
    await expect(main).not.toContainText(EXPECTED[locale].stale);
  });
}
