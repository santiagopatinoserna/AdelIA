import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

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

// Sending from the keyboard. The demo's textarea used to take Enter as a
// newline: an automated check typed a question, pressed Enter and the page
// stayed put, and on a phone the "Preguntar" button can sit behind the keyboard.
// Enter sends and Shift+Enter breaks the line, as in every chat the visitor
// already uses. The API call is answered by the test itself, so none of this
// needs an LLM key.
test.describe("public demo: sending from the keyboard", () => {
  const FAKE_ANSWER = {
    kind: "answer",
    answer: "Respuesta de prueba.",
    evidence_citations: [],
    disclaimer: "Aviso de prueba.",
  };

  // Records every question the page sends to /api/demo/ask and answers it.
  async function interceptAsk(page: Page, delayMs = 0) {
    const questions: string[] = [];
    await page.route("**/api/demo/ask", async (route) => {
      questions.push(JSON.parse(route.request().postData() ?? "{}").question);
      if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
      await route.fulfill({ json: FAKE_ANSWER });
    });
    return questions;
  }

  // `toBeEnabled` on the button is the hydration signal: it only flips once
  // React has processed the change, which is also when onKeyDown is attached.
  async function typeQuestion(page: Page, text: string) {
    const ask = page.getByTestId("demo-ask");
    const field = ask.getByLabel(/Escribe tu pregunta/);
    await field.fill(text);
    await expect(ask.getByRole("button", { name: "Preguntar" })).toBeEnabled();
    return field;
  }

  test("Enter sends the question and leaves the text as typed", async ({ page }) => {
    const questions = await interceptAsk(page);
    await page.goto("/es/demo");
    const field = await typeQuestion(page, "¿Es normal que regurgite?");

    await field.press("Enter");

    await expect.poll(() => questions).toEqual(["¿Es normal que regurgite?"]);
    await expect(page.getByTestId("demo-answer")).toBeVisible();
    // No stray line break appended by the keypress that sent it.
    await expect(field).toHaveValue("¿Es normal que regurgite?");
  });

  test("Shift+Enter breaks the line and does not send", async ({ page }) => {
    const questions = await interceptAsk(page);
    await page.goto("/es/demo");
    const field = await typeQuestion(page, "primera línea");

    await field.press("Shift+Enter");
    await field.pressSequentially("segunda línea");
    await expect(field).toHaveValue("primera línea\nsegunda línea");
    // If Shift+Enter had sent, "primera línea" would already be in the log.
    expect(questions).toEqual([]);

    await field.press("Enter");
    await expect.poll(() => questions).toEqual(["primera línea\nsegunda línea"]);
  });

  test("Enter on a question that is too short sends nothing and adds no line", async ({
    page,
  }) => {
    const questions = await interceptAsk(page);
    await page.goto("/es/demo");
    const ask = page.getByTestId("demo-ask");
    const field = ask.getByLabel(/Escribe tu pregunta/);
    await field.fill("ok");
    // The button is still disabled (under 3 characters): not hydrated-proof on
    // its own, so type a real question next and check only that one is sent.
    await field.press("Enter");
    await expect(field).toHaveValue("ok");

    await field.fill("¿Cuánto debe dormir?");
    await expect(ask.getByRole("button", { name: "Preguntar" })).toBeEnabled();
    await field.press("Enter");
    await expect.poll(() => questions).toEqual(["¿Cuánto debe dormir?"]);
  });

  test("a second Enter while the first answer is pending does not send twice", async ({
    page,
  }) => {
    const questions = await interceptAsk(page, 1_200);
    await page.goto("/es/demo");
    const field = await typeQuestion(page, "¿Es normal que regurgite?");

    await field.press("Enter");
    await expect(
      page.getByTestId("demo-ask").getByRole("button", { name: "Pensando…" }),
    ).toBeVisible();
    await field.press("Enter");

    await expect(page.getByTestId("demo-answer")).toBeVisible();
    expect(questions).toEqual(["¿Es normal que regurgite?"]);
    // The field kept its text and gained no line from the second Enter.
    await expect(field).toHaveValue("¿Es normal que regurgite?");
  });

  test("keyboard navigation and the amber focus ring still work: Tab reaches the button", async ({
    page,
  }) => {
    await page.goto("/es/demo");
    const ask = page.getByTestId("demo-ask");
    const field = await typeQuestion(page, "¿Es normal que regurgite?");
    await field.focus();
    await expect(field).toBeFocused();
    // The field keeps the product's two-tone amber ring (globals.css, spec 3.6).
    const ring = await field.evaluate((el) => getComputedStyle(el).outlineColor);
    expect(ring, "the field's focus ring is the product's amber").toBe("rgb(163, 110, 31)");

    await page.keyboard.press("Tab");
    await expect(ask.getByRole("button", { name: "Preguntar" })).toBeFocused();
  });

  test("with the phone keyboard up, the field and 'Preguntar' stay on screen", async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await context.newPage();
    await interceptAsk(page);
    await page.goto("/es/demo");
    const ask = page.getByTestId("demo-ask");
    const field = await typeQuestion(page, "¿Es normal que regurgite?");
    const button = ask.getByRole("button", { name: "Preguntar" });

    // Focus again now that React is listening, then shrink the viewport to what
    // is left above a ~424 px keyboard (the same emulation as the dashboard's
    // keyboard check in mobile.spec.ts).
    await field.evaluate((el) => (el as HTMLTextAreaElement).blur());
    await field.focus();
    await page.setViewportSize({ width: 390, height: 420 });

    await expect
      .poll(
        async () => {
          const f = await field.boundingBox();
          const b = await button.boundingBox();
          return f !== null && b !== null && f.y >= 0 && b.y + b.height <= 420;
        },
        { message: "field and button both inside the 420 px left above the keyboard" },
      )
      .toBe(true);
    await context.close();
  });
});
