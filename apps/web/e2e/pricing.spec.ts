import { expect, test } from "@playwright/test";

// Audit 4.10: the landing sold a third plan, "Con especialista" at 16 EUR a
// month, whose button (href "/dashboard") walked the buyer to the 8 EUR
// checkout, because config.py declares exactly one stripe_price_id. No
// paediatrician was under contract, and the fee for the review existed
// nowhere in the code or the documents.
//
// This spec is the guard against it coming back by copy-paste. It has to hold
// in the three languages, because the tier existed in all three.

const LOCALES = ["es", "en", "fr"] as const;

test.describe("landing pricing", () => {
  for (const locale of LOCALES) {
    test(`${locale}: two plans, and no button for a service that does not exist`, async ({
      page,
    }) => {
      await page.goto(`/${locale}`);
      const pricing = page.locator("section#pricing");
      await expect(pricing).toBeVisible();

      // Exactly two plan cards: Open Source and Managed.
      await expect(pricing.getByRole("heading", { level: 3 })).toHaveCount(2);

      const text = (await pricing.textContent()) ?? "";
      expect(text).not.toMatch(/16\s*€|€\s*16/);
      expect(text).not.toMatch(/especialista|specialist|spécialiste/i);
    });
  }

  test("es: the two surviving plans still sell what they always sold", async ({
    page,
  }) => {
    await page.goto("/es");
    const pricing = page.locator("section#pricing");

    await expect(pricing.getByRole("heading", { level: 3, name: "Open Source" })).toBeVisible();
    await expect(pricing.getByRole("heading", { level: 3, name: "Gestionado" })).toBeVisible();
    await expect(pricing.getByText("8€", { exact: true })).toBeVisible();
    // The trial no longer asks for a card (audit 4.7), so the landing says so.
    await expect(pricing.getByText("Prueba gratis 30 días, sin tarjeta")).toBeVisible();
  });

  test("the landing offers the demo without an account", async ({ page }) => {
    await page.goto("/es");

    const demoLink = page.getByRole("link", { name: "Ver la demo sin cuenta" }).first();
    await expect(demoLink).toBeVisible();
    await demoLink.click();
    await expect(page).toHaveURL(/\/es\/demo/);
    await expect(page.getByTestId("demo-ask")).toBeVisible();
  });
});
