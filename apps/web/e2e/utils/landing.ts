import { expect, type Page } from "@playwright/test";

// On a phone the landing folds everything after the proof behind one "Ver más"
// (components/landing-fold.tsx). The toggle is server-rendered, so it is
// visible before React has attached its click handler: a bare click right after
// `goto` can land on a button that does nothing yet. Retry until the panel
// really reports itself open.
export async function openLandingFold(page: Page) {
  const toggle = page.getByTestId("landing-fold-toggle");
  await expect(async () => {
    if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true", { timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
}
