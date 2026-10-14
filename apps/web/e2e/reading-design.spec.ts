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

test("demo: the question is reachable before reading the sample record on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/es/demo");
  const field = page.locator("#demo-question");
  const box = await field.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(760);
});

test("demo: source titles and attribution remain readable without truncation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/es/demo");
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
