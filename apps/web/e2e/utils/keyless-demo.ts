import type { Page } from "@playwright/test";

// Since 2026-11-06 ("la demo es la app real") a question on the landing opens
// the real panel as a guest (components/demo-ask.tsx). The landing still draws
// an answer itself, through the keyless /api/demo/ask, when the guest cannot
// be created (the API's anti-bot brake, an outage), so the question is never
// lost. The specs written for that answer keep covering it by refusing the
// guest sign-in, exactly as the brake does; e2e/guest-journey.spec.ts covers
// the main path.
export async function forceKeylessDemo(page: Page): Promise<void> {
  await page.route("**/api/auth/callback/guest**", (route) =>
    route.fulfill({
      status: 429,
      contentType: "application/json",
      body: JSON.stringify({ url: "http://localhost/api/auth/error?error=RateLimited" }),
    }),
  );
}
