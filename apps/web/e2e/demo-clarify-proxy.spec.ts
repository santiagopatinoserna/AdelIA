import { expect, test } from "@playwright/test";
import es from "../messages/es.json";

// The clarify loop through the REAL proxy (app/api/demo/ask/route.ts) and the
// real API, with nothing mocked. 2026-10-23: the proxy forwarded only
// `question` and `locale`, so her button never reached the API and every
// press asked the same question again, forever. The API decides this turn by
// rules alone (no model, no key), so it runs in CI: a fever with a reading is
// never asked for the reading again. Without an LLM key the answer itself
// may fail upstream (503); what this test pins is that the question is not
// repeated.
test.use({ viewport: { width: 390, height: 844 } });

test("es: pressing a value through the real proxy never repeats the question", async ({ page }) => {
  await page.goto("/es");
  await page.locator("#demo-question").fill("Tiene fiebre desde esta mañana, ¿qué hago?");
  await page.getByRole("button", { name: es.demo.askCta, exact: true }).click();
  const box = page.getByTestId("demo-clarify");
  await expect(box).toBeVisible({ timeout: 30_000 });

  const answered = page.waitForResponse(
    (r) => r.url().endsWith("/api/demo/ask") && r.request().method() === "POST",
    { timeout: 60_000 },
  );
  await box.getByTestId("clarify-option").nth(2).click();
  const response = await answered;
  expect(JSON.parse(response.request().postData()!)).toMatchObject({
    clarification: { field: "temperature", value: "39+" },
  });
  // What came back is anything but the same question again...
  const body = await response.json().catch(() => ({}));
  expect(body.kind).not.toBe("clarify");
  // ...and the page shows the answer or the "unavailable" note, not the buttons.
  const demo = page.getByTestId("demo-ask");
  await expect(page.getByTestId("demo-loading")).toHaveCount(0, { timeout: 60_000 });
  await expect(demo.getByTestId("demo-answer").or(demo.getByRole("alert"))).toBeVisible();
  await expect(page.getByTestId("demo-clarify")).toHaveCount(0);
});
