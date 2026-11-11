import { expect, test, type Browser } from "@playwright/test";
import es from "../messages/es.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";
import { parseAgentBlocks } from "@/lib/agent-types";
import { seedUserAndSessionCookie } from "./utils/session";

// The battery with the real model (2026-11-11): 7.0 s median to the first word,
// 20.2 s at p95, all of it under «Pensando…». The API now says what the turn is
// doing (status frames): searching, then how many sources the answer is written
// from. The stream is simulated in the page, frame by frame, so this pins the
// panel, not the API, and needs no model.
test.use({ viewport: { width: 390, height: 844 } });

const CATALOGS = { es, en, fr } as const;

function collect(raw: string) {
  let buffer = raw;
  return [...parseAgentBlocks(() => buffer, (rest) => { buffer = rest; })];
}

test("parses a status frame", () => {
  const [ev] = collect('event: status\ndata: {"stage":"writing","sources":3}\n\n');
  expect(ev).toEqual({ type: "status", stage: "writing", sources: 3 });
  const [bare] = collect('event: status\ndata: {"stage":"searching"}\n\n');
  expect(bare).toEqual({ type: "status", stage: "searching", sources: 0 });
});

/** The panel with /agent/turn answering frame by frame, as the API streams it. */
async function openWithSlowStream(browser: Browser, locale: string, answer: string,
                                  scheme: "light" | "dark" = "light") {
  const { cookie } = await seedUserAndSessionCookie(`e2e-agent-wait-${locale}-${Date.now()}@adelia.test`);
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: scheme });
  await context.addCookies([cookie]);
  await context.addInitScript((text: string) => {
    const original = window.fetch.bind(window);
    const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
    const frames: [number, string][] = [
      [0, frame("start", {})],
      [0, frame("status", { stage: "searching", sources: 0 })],
      [1500, frame("status", { stage: "writing", sources: 3 })],
      [2500, frame("token", { content: text })],
      [0, frame("final", { citations: [], evidence_citations: [] })],
    ];
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (!url.includes("/api/backend/agent/turn")) return original(input, init);
      const encoder = new TextEncoder();
      const body = new ReadableStream<Uint8Array>({
        async start(controller) {
          for (const [wait, chunk] of frames) {
            await new Promise((r) => setTimeout(r, wait));
            controller.enqueue(encoder.encode(chunk));
          }
          controller.close();
        },
      });
      return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
    };
  }, answer);
  const page = await context.newPage();
  await page.goto(`/${locale}/dashboard`);
  return { page, context };
}

for (const locale of ["es", "en", "fr"] as const) {
  test(`${locale}: the wait says it is searching, then from how many sources it writes`, async ({ browser }) => {
    const t = CATALOGS[locale].agent;
    const answer = "Ofrécele el pecho a demanda [ev_1].";
    const { page, context } = await openWithSlowStream(browser, locale, answer);
    const box = page.getByPlaceholder(t.placeholder);
    await box.fill("cada cuanto tiene q comer");
    await box.press("Enter");

    const wait = page.getByTestId("agent-wait");
    await expect(wait).toHaveText(t.statusSearching);
    const writing = t.statusWriting.match(/other \{(.*)\}\}$/)![1].replace("#", "3");
    await expect(wait).toHaveText(writing);
    await expect(wait).toHaveAttribute("role", "status");
    await expect(page.getByText("Ofrécele el pecho a demanda")).toBeVisible();
    await expect(wait).toHaveCount(0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await context.close();
  });
}

test("the writing stage reads at 390x844, light and dark", async ({ browser }, testInfo) => {
  for (const scheme of ["light", "dark"] as const) {
    const { page, context } = await openWithSlowStream(browser, "es", "Ofrécele el pecho [ev_1].", scheme);
    const box = page.getByPlaceholder(es.agent.placeholder);
    await box.fill("cada cuanto tiene q comer");
    await box.press("Enter");
    await expect(page.getByTestId("agent-wait")).toHaveText("He encontrado 3 fuentes. Escribiendo…");
    const color = await page.getByTestId("agent-wait").evaluate((el) => getComputedStyle(el).color);
    expect(color).not.toBe(await page.evaluate(() => getComputedStyle(document.body).backgroundColor));
    await page.screenshot({ path: testInfo.outputPath(`agent-wait-writing-es-390-${scheme}.png`) });
    await context.close();
  }
});
