import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// The public demo (audit 4.6): the only screen that shows the product working
// without an email, a magic link and a credit card, in that order.
//
// No session anywhere in this file. If any assertion here starts needing one,
// the page has stopped being what it exists to be.

test.describe("public demo", () => {
  test("shows a fictional baby's record, labelled as a demo, with no account", async ({
    page,
  }) => {
    await page.goto("/es/demo");

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // Marked as a demo more than once: the badge on the card and the banner
    // the API itself writes. A demo of a baby-health product that reads as a
    // real child's file is a liability, not a demo.
    const record = page.getByTestId("demo-record");
    await expect(record).toBeVisible();
    await expect(record.getByText("Demo", { exact: true })).toBeVisible();
    await expect(record.getByText(/bebé inventado/i)).toBeVisible();
    await expect(record.getByText(/Datos ficticios/i)).toBeVisible();
    // The record itself: report, labs, recorded appointment, diary.
    await expect(record.getByText(/Informe de la revisión de los 4 meses/)).toBeVisible();
    await expect(record.getByText(/Hemoglobina 10,8/)).toBeVisible();
    await expect(record.getByText(/Consulta grabada/)).toBeVisible();

    // ...and the promise that nothing is stored.
    await expect(page.getByText(/Nada de lo que escribas aquí se guarda/)).toBeVisible();
  });

  test("offers suggested questions and a free-text box", async ({ page }) => {
    await page.goto("/es/demo");

    const ask = page.getByTestId("demo-ask");
    await expect(ask.getByLabel(/Escribe tu pregunta/)).toBeVisible();
    const submit = ask.getByRole("button", { name: "Preguntar" });
    // Nothing typed: nothing to send.
    await expect(submit).toBeDisabled();
    await ask.getByLabel(/Escribe tu pregunta/).fill("¿Es normal que regurgite?");
    await expect(submit).toBeEnabled();

    // At least three ready-made questions, straight from the API fixture.
    const suggestions = ask.locator("ul button");
    expect(await suggestions.count()).toBeGreaterThanOrEqual(3);
  });

  test("asking never leaves the visitor without an answer or an explanation", async ({
    page,
  }) => {
    await page.goto("/es/demo");
    const ask = page.getByTestId("demo-ask");
    await ask.locator("ul button").first().click();

    // Either the answer renders (a stack with an LLM key) or the page says
    // why it cannot (no key, budget spent, provider down). What must never
    // happen is a spinner that stops with nothing on screen.
    const answer = page.getByTestId("demo-answer");
    // Scoped to the ask panel: Next's own route announcer is also role=alert,
    // and an unscoped locator matches it too (strict-mode violation).
    const alert = ask.getByRole("alert");
    await expect(answer.or(alert)).toBeVisible({ timeout: 60_000 });
    await expect(ask.getByRole("button", { name: "Pensando…" })).toHaveCount(0);
  });

  test("is indexable: in the sitemap, allowed by robots, in three languages", async ({
    page,
    request,
  }) => {
    const sitemap = await (await request.get("/sitemap.xml")).text();
    for (const locale of ["es", "en", "fr"]) {
      expect(sitemap).toContain(`/${locale}/demo`);
    }
    const robots = await (await request.get("/robots.txt")).text();
    expect(robots).not.toContain("/demo");

    for (const [locale, heading] of [
      ["en", /Ask what you would ask your pediatrician/i],
      ["fr", /Pose la question que tu poserais/i],
    ] as const) {
      await page.goto(`/${locale}/demo`);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    }
  });

  test("is accessible in light and dark", async ({ browser }) => {
    for (const colorScheme of ["light", "dark"] as const) {
      const context = await browser.newContext({
        colorScheme,
        // The card entrance (ad-rise) fades text in; sampling mid-fade reads
        // a lighter ink than the stylesheet declares (commit a664166).
        reducedMotion: "reduce",
      });
      const page = await context.newPage();
      await page.goto("/es/demo");
      await page.waitForLoadState("networkidle").catch(() => {});
      const results = await new AxeBuilder({ page }).analyze();
      const blocking = results.violations.filter((v) =>
        ["serious", "critical"].includes(v.impact ?? ""),
      );
      expect(
        blocking,
        `${colorScheme}: ${blocking.map((v) => v.id).join(", ")}`,
      ).toEqual([]);
      await context.close();
    }
  });
});
