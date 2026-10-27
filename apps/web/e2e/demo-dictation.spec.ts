import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser, type Page } from "@playwright/test";

import enMessages from "@/messages/en.json";
import esMessages from "@/messages/es.json";
import frMessages from "@/messages/fr.json";

// Voice dictation in the public demo field. The demo has no account, so audio
// never leaves the phone: the browser's own Web Speech API transcribes and we
// only ever see text. The button exists only where the API exists, and the
// transcript lands in the field for her to correct; she still presses send.
//
// Chrome exposes SpeechRecognition but has no speech to hear in a test, so a
// scripted stand-in is injected before any page script runs. It records the
// options it was started with and replays the results it is told to emit.

const MESSAGES = { es: esMessages, en: enMessages, fr: frMessages } as const;
const LOCALES = ["es", "en", "fr"] as const;
const LANG = { es: "es-ES", en: "en-GB", fr: "fr-FR" } as const;
const PHONE = { width: 390, height: 844 };
const TAP_MIN = 44 - 0.05;

const STUB = `
  class FakeRecognition {
    constructor() {
      this.lang = ""; this.interimResults = false; this.continuous = true;
      this.onresult = null; this.onerror = null; this.onend = null;
      window.__dictation = this;
    }
    start() { this.started = (this.started || 0) + 1; this.running = true;
      window.__dictationStarts = this.started;
      window.__dictationOptions = { lang: this.lang, interimResults: this.interimResults, continuous: this.continuous }; }
    stop() { this.stopped = (this.stopped || 0) + 1; this.running = false; this.onend && this.onend(); }
    abort() { this.stop(); }
    emit(text, isFinal) {
      const alt = { transcript: text, confidence: 0.9 };
      const result = Object.assign([alt], { isFinal, length: 1, item: () => alt });
      const results = Object.assign([result], { length: 1, item: () => result });
      this.onresult && this.onresult({ resultIndex: 0, results });
    }
    fail(error) { this.onerror && this.onerror({ error }); this.running = false; this.onend && this.onend(); }
  }
  window.SpeechRecognition = FakeRecognition;
  window.webkitSpeechRecognition = FakeRecognition;
`;

const WITHOUT_API = `
  Object.defineProperty(window, "SpeechRecognition", { value: undefined, configurable: true });
  Object.defineProperty(window, "webkitSpeechRecognition", { value: undefined, configurable: true });
`;

async function phone(browser: Browser, init: string, scheme: "light" | "dark" = "light") {
  const context = await browser.newContext({
    viewport: PHONE, isMobile: true, hasTouch: true, reducedMotion: "reduce", colorScheme: scheme,
  });
  await context.addInitScript(init);
  const page = await context.newPage();
  return { context, page };
}

const mic = (page: Page, locale: keyof typeof MESSAGES) =>
  page.getByTestId("demo-ask").getByRole("button", { name: MESSAGES[locale].demo.dictate, exact: true });

const emit = (page: Page, text: string, isFinal: boolean) =>
  page.evaluate(([t, f]) => (window as any).__dictation.emit(t, f), [text, isFinal] as const);

test.describe("dictation in the demo field", () => {
  for (const locale of LOCALES) {
    test(`${locale}: no button without the Web Speech API`, async ({ browser }) => {
      const { context, page } = await phone(browser, WITHOUT_API);
      await page.goto(`/${locale}`);
      await expect(page.locator("#demo-question")).toBeVisible();
      await expect(mic(page, locale)).toHaveCount(0);
      await context.close();
    });

    test(`${locale}: the button appears with the API, inside the field, 44 px`, async ({ browser }) => {
      const { context, page } = await phone(browser, STUB);
      await page.goto(`/${locale}`);
      const button = mic(page, locale);
      await expect(button).toBeVisible();
      await expect(button).toHaveAttribute("aria-pressed", "false");
      const box = (await button.boundingBox())!;
      expect(box.width).toBeGreaterThanOrEqual(TAP_MIN);
      expect(box.height).toBeGreaterThanOrEqual(TAP_MIN);
      const field = (await page.locator("#demo-question").boundingBox())!;
      expect(box.x + box.width).toBeLessThanOrEqual(field.x + field.width + 0.5);
      expect(box.y).toBeGreaterThanOrEqual(field.y - 0.5);
      expect(box.y + box.height).toBeLessThanOrEqual(field.y + field.height + 0.5);
      // Typed text and placeholder stop before the button, never under it.
      const paddingRight = await page.locator("#demo-question")
        .evaluate((el) => parseFloat(getComputedStyle(el).paddingRight));
      expect(paddingRight).toBeGreaterThanOrEqual(box.width + 4);
      // The first screen stays whole: field and send still in view, no sideways scroll.
      const send = page.getByRole("button", { name: MESSAGES[locale].demo.askCta, exact: true });
      await expect(send).toBeInViewport({ ratio: 1 });
      const w = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth,
      }));
      expect(w.scroll).toBe(w.client);
      await context.close();
    });

    test(`${locale}: interim text is shown, the final text lands in the field, nothing is sent`, async ({ browser }) => {
      const { context, page } = await phone(browser, STUB);
      let asked = 0;
      await page.route("**/api/demo/ask", (route) => { asked += 1; return route.fulfill({ json: {
        kind: "answer", answer: "Texto.", evidence_citations: [], disclaimer: "Aviso.",
      } }); });
      await page.goto(`/${locale}`);
      const field = page.locator("#demo-question");
      await field.fill("Desde ayer");
      await mic(page, locale).click();
      await expect(mic(page, locale)).toHaveAttribute("aria-pressed", "true");
      expect(await page.evaluate(() => (window as any).__dictationOptions)).toEqual({
        lang: LANG[locale], interimResults: true, continuous: false,
      });

      await emit(page, "tiene mo", false);
      const interim = page.getByTestId("dictation-interim");
      await expect(interim).toHaveText("tiene mo");
      await expect(field).toHaveValue("Desde ayer");

      await emit(page, "tiene mocos", true);
      await page.evaluate(() => (window as any).__dictation.onend());
      await expect(field).toHaveValue("Desde ayer tiene mocos");
      await expect(interim).toHaveCount(0);
      await expect(mic(page, locale)).toHaveAttribute("aria-pressed", "false");
      await page.waitForTimeout(300);
      expect(asked).toBe(0);
      await expect(page.getByTestId("demo-answer")).toHaveCount(0);
      await context.close();
    });

    test(`${locale}: tapping again stops listening`, async ({ browser }) => {
      const { context, page } = await phone(browser, STUB);
      await page.goto(`/${locale}`);
      await mic(page, locale).click();
      await expect(mic(page, locale)).toHaveAttribute("aria-pressed", "true");
      await mic(page, locale).click();
      await expect(mic(page, locale)).toHaveAttribute("aria-pressed", "false");
      expect(await page.evaluate(() => (window as any).__dictation.stopped)).toBe(1);
      await context.close();
    });

    test(`${locale}: when it cannot listen, one short line, and the field stays usable`, async ({ browser }) => {
      const { context, page } = await phone(browser, STUB);
      await page.goto(`/${locale}`);
      await mic(page, locale).click();
      await page.evaluate(() => (window as any).__dictation.fail("not-allowed"));
      const alert = page.getByTestId("demo-ask").getByRole("alert");
      await expect(alert).toHaveText(MESSAGES[locale].demo.dictateError);
      await expect(mic(page, locale)).toHaveAttribute("aria-pressed", "false");
      await page.locator("#demo-question").fill("Pregunta escrita");
      await expect(page.getByRole("button", { name: MESSAGES[locale].demo.askCta, exact: true })).toBeEnabled();
      await context.close();
    });
  }

  test("a11y: idle and listening, light and dark", async ({ browser }) => {
    for (const scheme of ["light", "dark"] as const) {
      const { context, page } = await phone(browser, STUB, scheme);
      await page.goto("/es");
      await page.waitForLoadState("networkidle").catch(() => {});
      for (const state of ["idle", "listening"]) {
        if (state === "listening") {
          await mic(page, "es").click();
          await emit(page, "tiene mo", false);
        }
        const results = await new AxeBuilder({ page }).analyze();
        const bad = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
        expect(bad.map((v) => `${v.id}: ${v.nodes.length}`), `axe, ${scheme}, ${state}`).toEqual([]);
      }
      await context.close();
    }
  });
});
