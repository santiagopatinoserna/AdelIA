import { expect, type Locator } from "@playwright/test";

// The one way the e2e suite writes a question and sends it: the landing's
// field, the panel's and the chat's. ask-helper.spec.ts fails on a spec that
// does it by hand.
//
// The server-rendered field is on screen before React hydrates it. CI under
// load handed specs such a page again and again, each time a different one
// (usability-findings in #72, panel-clean's red flag after it): the text went
// in, the Enter or the tap went nowhere, or the question left at hydration,
// the moment public/sw.js registers and takes the page, and the mocked turn
// reached the real API past page.route ("Ahora no puedo responderte").
// playwright.config.ts blocks the service worker for every context; ask()
// waits for React's handlers on the field and fails loudly if a worker still
// controls the page.

// React attaches its props to a DOM node when it hydrates it.
export const isHydrated = (el: Locator) =>
  el.evaluate((node) => Object.keys(node).some((k) => k.startsWith("__reactProps$")));

export async function waitHydrated(el: Locator) {
  await el.waitFor({ state: "attached" });
  // Generous: a loaded CI runner hydrates in seconds, not in Playwright's 5.
  await expect.poll(() => isHydrated(el), { timeout: 30_000, message: "React never hydrated it" })
    .toBe(true);
}

// Fills `field` and sends with Enter, or by tapping `send` (the landing's
// "Preguntar"), once React has hydrated the field.
export async function ask(field: Locator, text: string, { send }: { send?: Locator } = {}) {
  await waitHydrated(field);
  expect(await field.page().evaluate(() => Boolean(navigator.serviceWorker?.controller)),
    "a service worker controls the page and can carry the request past page.route").toBe(false);
  await field.fill(text);
  if (send) await send.click();
  else await field.press("Enter");
}
