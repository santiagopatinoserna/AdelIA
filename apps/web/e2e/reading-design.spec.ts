import { expect, test } from "@playwright/test";

for (const locale of ["es", "en", "fr"]) {
  test(`landing: the main idea fits in four lines on a phone (${locale})`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/${locale}`);
    const heading = page.getByRole("heading", { level: 1 });
    const lines = await heading.evaluate((el) => {
      const style = getComputedStyle(el);
      return el.getBoundingClientRect().height / parseFloat(style.lineHeight);
    });
    expect(lines).toBeLessThanOrEqual(4.1);
  });
}

// The demo is the landing now ("/es"), so the question has to sit higher than
// the old 760 px ceiling: field, "Preguntar" and the first suggested question
// all in the first screen of a 390x844 phone (one tap to a cited answer).
test("landing: the question and a suggested question are in the first screen of a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/es");
  const field = page.locator("#demo-question");
  const box = await field.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(380);
  const first = (await page.locator('[data-testid="demo-ask"] ul button').first().boundingBox())!;
  expect(first.y + first.height).toBeLessThanOrEqual(844);
});

test("demo: source titles and attribution remain readable without truncation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/es");
  await page.locator("#demo-question").fill("Mi bebé de 2 meses tiene fiebre de 38,2 grados.");
  await page.getByRole("button", { name: "Preguntar", exact: true }).click();
  const answer = page.getByTestId("demo-answer");
  await expect(answer).toBeVisible();
  const source = answer.getByRole("link", { name: /Fiebre en menores de 5 años/ });
  const title = source.getByText(/Fiebre en menores de 5 años/);
  const titleStyle = await title.evaluate((el) => {
    const style = getComputedStyle(el);
    return { size: parseFloat(style.fontSize), whiteSpace: style.whiteSpace };
  });
  expect(titleStyle.size).toBeGreaterThanOrEqual(14);
  expect(titleStyle.whiteSpace).not.toBe("nowrap");
  const attribution = source.getByText(/National Institute for Health and Care Excellence/);
  expect(await attribution.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(12);
});

test("demo: each source is one row and its literal passage opens on tap", async ({ page }) => {
  const quote = "La regurgitación suele alcanzar su pico hacia los 4 meses.";
  await page.route("**/api/demo/ask", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        kind: "answer",
        answer: "Es habitual a esa edad [ev_1].",
        evidence_citations: [
          {
            tag: "ev_1",
            chunk_id: "c1",
            title: "Reflujo del lactante: historia natural",
            organization: "NASPGHAN-ESPGHAN",
            year: 2018,
            url: "https://example.org/guia",
            snippet: quote,
          },
        ],
      }),
    }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/es");
  await page.locator("#demo-question").fill("¿Es normal que regurgite después de las tomas?");
  await page.getByRole("button", { name: "Preguntar", exact: true }).click();

  const answer = page.getByTestId("demo-answer");
  const depth = answer.getByTestId("answer-depth");
  await depth.locator(":scope > summary").click();
  const source = depth.locator("details").first();
  // The outbound link also names the source for screen readers; select the visible title exactly.
  await expect(source.getByText("Reflujo del lactante: historia natural", { exact: true })).toBeVisible();
  await expect(source.getByText("NASPGHAN-ESPGHAN (2018)").first()).toBeVisible();
  // Closed: the quotation is in the page but not on screen.
  await expect(source.getByText(quote)).toBeHidden();
  expect((await source.boundingBox())!.height).toBeLessThan(110);

  await source.locator("summary").click();
  await expect(source.getByText(quote)).toBeVisible();
  const link = source.getByRole("link");
  await expect(link).toHaveAttribute("href", "https://example.org/guia");
  expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(43.9);
});
