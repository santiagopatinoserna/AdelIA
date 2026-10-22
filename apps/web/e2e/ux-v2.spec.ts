import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { homedir } from "node:os";
import { join } from "node:path";

// UI fixtures only: these responses do not verify retrieval or clinical quality.
const shots = join(homedir(), "dev/adelia-design/shots/ux-v2");
const fixture = {
  kind: "answer",
  answer: "Respuesta simulada para comprobar la interfaz. No es una recomendación clínica. [E1]",
  evidence_citations: [{
    tag: "E1", source_id: "test", chunk_id: "test-1",
    title: "Fuente de prueba: título completo y largo, sin recortes ni puntos suspensivos",
    organization: "Organización de prueba", year: 2026,
    url: "https://example.org/clinical-source", snippet: "Texto literal de prueba.\nSegunda línea conservada.",
  }],
  disclaimer: "Aviso clínico de prueba: no sustituye al pediatra.",
};

for (const width of [390, 375, 1440]) {
  test(`keyboard, pending, answer and sources at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    let release!: () => void;
    let requests = 0;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    await page.route("**/api/demo/ask", async (route) => {
      requests += 1;
      expect(route.request().postDataJSON().question).toBe("Pregunta de prueba\nsegunda línea");
      expect(route.request().headers().cookie).toBeUndefined();
      await gate;
      await route.fulfill({ json: fixture });
    });
    await page.clock.install();
    await page.goto("/es");
    const ask = page.getByTestId("demo-ask");
    const field = ask.getByLabel(/Escribe tu pregunta/);
    await expect(field).toBeVisible();
    await field.fill("ok");
    await expect(ask.getByRole("button", { name: "Preguntar", exact: true })).toBeDisabled();
    await field.fill("Pregunta de prueba");
    await expect(ask.getByRole("button", { name: "Preguntar", exact: true })).toBeEnabled();
    await field.press("Shift+Enter");
    await field.pressSequentially("segunda línea");
    await field.press("Enter");
    await expect(page.getByTestId("demo-loading")).toContainText("Esperando respuesta");
    await field.press("Enter");
    await page.screenshot({ path: `${shots}/ask-loading-${width}.png`, fullPage: true });
    // No time-based claim that generation has started.
    await page.clock.fastForward(11000);
    await expect(page.getByTestId("demo-loading")).toContainText("sigue pendiente");
    await expect(ask).not.toContainText("Redactando");
    await page.evaluate(() => { (document.activeElement as HTMLElement)?.blur(); window.scrollTo(0, 0); });
    const before = await page.evaluate(() => window.scrollY);
    release();
    await expect(page.getByTestId("demo-answer")).toBeVisible();
    expect(await page.evaluate(() => window.scrollY)).toBe(before);
    expect(requests).toBe(1);
    await expect(ask.getByRole("status")).toContainText("disponible");
    await expect(ask.getByText(fixture.disclaimer)).toBeVisible();
    const depth = ask.getByTestId("answer-depth");
    await depth.locator(":scope > summary").click();
    const source = depth.locator("details");
    await expect(source.locator("summary")).toContainText(fixture.evidence_citations[0].title);
    await expect(source.locator("blockquote")).not.toBeVisible();
    await source.locator("summary").focus();
    await page.keyboard.press("Enter");
    await expect(source.locator("blockquote")).toBeVisible();
    await expect(source.getByRole("link")).toHaveAttribute("href", "https://example.org/clinical-source");
    expect(await source.locator("blockquote").evaluate((el) => getComputedStyle(el).fontSize)).toBe("14px");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `${shots}/ask-answer-sources-${width}.png`, fullPage: true });
    const audit = await new AxeBuilder({ page }).include('[data-testid="demo-ask"]').analyze();
    expect(audit.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? ""))).toEqual([]);
  });
}

test("error retry preserves the submitted question, not an edited draft", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/demo/ask", async (route) => {
    requests++;
    expect(route.request().postDataJSON().question).toBe("Pregunta original");
    await route.fulfill(requests === 1 ? { status: 503, json: {} } : { json: fixture });
  });
  await page.goto("/es");
  const ask = page.getByTestId("demo-ask");
  await ask.getByLabel(/Escribe tu pregunta/).fill("Pregunta original");
  await ask.getByRole("button", { name: "Preguntar", exact: true }).click();
  await expect(ask.getByRole("alert")).toContainText("no está disponible");
  await page.screenshot({ path: `${shots}/ask-error.png`, fullPage: true });
  await ask.getByLabel(/Escribe tu pregunta/).fill("Borrador editado");
  await ask.getByRole("button", { name: "Reintentar la misma pregunta" }).click();
  await expect(page.getByTestId("demo-answer")).toBeVisible();
  await expect(ask.getByLabel(/Escribe tu pregunta/)).toHaveValue("Borrador editado");
  expect(requests).toBe(2);
});

for (const status of [429, 500]) {
  test(`HTTP ${status} leaves an actionable error`, async ({ page }) => {
    await page.route("**/api/demo/ask", (route) => route.fulfill({ status, json: {} }));
    await page.goto("/es");
    const ask = page.getByTestId("demo-ask");
    await ask.getByLabel(/Escribe tu pregunta/).fill("Pregunta de prueba");
    await ask.getByRole("button", { name: "Preguntar", exact: true }).click();
    await expect(ask.getByRole("alert")).toContainText(status === 429 ? "límite" : "Algo ha fallado");
    await expect(ask.getByRole("button", { name: "Reintentar la misma pregunta" })).toBeEnabled();
  });
}

test("a request timeout stops waiting and offers retry", async ({ page }) => {
  await page.clock.install();
  await page.route("**/api/demo/ask", () => new Promise<void>(() => {}));
  await page.goto("/es");
  const ask = page.getByTestId("demo-ask");
  await ask.getByLabel(/Escribe tu pregunta/).fill("Pregunta sin respuesta");
  await ask.getByRole("button", { name: "Preguntar", exact: true }).click();
  await expect(page.getByTestId("demo-loading")).toBeVisible();
  await page.clock.fastForward(61000);
  await expect(ask.getByRole("alert")).toContainText("Algo ha fallado");
  await expect(page.getByTestId("demo-loading")).not.toBeVisible();
  await expect(ask.getByRole("button", { name: "Reintentar la misma pregunta" })).toBeEnabled();
});

for (const kind of ["red_flag", "no_evidence", "evidence_only"]) {
  test(`server decision preserved: ${kind}`, async ({ page }) => {
    await page.route("**/api/demo/ask", (route) => route.fulfill({ json: { ...fixture, kind } }));
    await page.clock.install();
    await page.goto("/es");
    const ask = page.getByTestId("demo-ask");
    await ask.locator("ul button").first().click();
    await expect(page.getByTestId("demo-answer")).toBeVisible();
    await expect(ask.getByText(fixture.disclaimer)).toBeVisible();
    if (kind === "red_flag") await expect(ask.getByText(/No puedo valorar a tu bebé a distancia/)).toBeVisible();
    if (kind === "evidence_only") await expect(ask.getByText(/No hemos podido redactar/)).toBeVisible();
    else await expect(ask.getByText(fixture.answer)).toBeVisible();
  });
}
