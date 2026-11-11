import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import es from "../messages/es.json";
import { ask } from "./utils/ask";
import { forceKeylessDemo } from "./utils/keyless-demo";
import { seedUserAndSessionCookie } from "./utils/session";

// The landing's own answer, drawn when no guest can be created (see the helper).
test.beforeEach(async ({ page }) => forceKeylessDemo(page));

// Prod journey 2026-11-06: a mother read "... limpia y seca [ev_1][ev_2]" in
// the answer and "[2]" in her history, programmer text in the middle of a
// sentence. The marker becomes a small number that matches the number on its
// source card (evidence) or on its record (her history, drawn differently),
// says "Fuente 1" or "Historial 2" to a screen reader, and on a tap takes her
// to that card, opening it if folded. Presentation only: the model's text is
// the same, character for character, and stays in the DOM.
// Responses are mocked: this pins the page, not the model.

test.use({ viewport: { width: 390, height: 844 } });

const SHOTS = join(homedir(), "dev/adelia-design/shots/citations");
mkdirSync(SHOTS, { recursive: true });
const PHASE = process.env.SHOTS_PHASE ?? "after";
const disclaimer = "AdelIA no sustituye a tu pediatra. Verifica con tu médico antes de tomar decisiones clínicas.";

const ev = (n: number, title: string, org: string) => ({
  tag: `ev_${n}`, source_id: `src-${n}`, chunk_id: `chunk-${n}`, title, organization: org,
  year: 2024, url: `https://example.org/source-${n}`, tier: "evidence",
  snippet: `Resumen de la fuente ${n}: lo que dice sobre la dermatitis del pañal.`,
});
const citations = [
  ev(1, "Dermatitis del pañal: cuidados de la piel en el lactante", "Asociación Española de Pediatría"),
  ev(2, "Napkin dermatitis: clinical knowledge summary", "NICE"),
  ev(3, "Cuándo consultar por una dermatitis del pañal", "Comité de Pediatría"),
  {
    tag: "ex_1", source_id: "exp-1", chunk_id: "exp-chunk-1", tier: "experience",
    title: "Lo que nos funcionó con la dermatitis", organization: "Blog de una madre", year: 2025,
    url: "https://example.org/blog", snippet: "Le dejábamos un rato sin pañal después del baño.",
  },
];
const p = es.demo.plan;
const planAnswer = [
  "Es frecuente y suele poder tratarse en casa [ev_2]. Lo principal es que la piel quede limpia y seca [ev_1][ev_2].",
  "", `## ${p.today}`, "- Cambia el pañal en cuanto lo moje [ev_1].", "- Deja la piel al aire unos minutos [ev_2].",
  "", `## ${p.watch}`, "- Si aparecen granitos fuera de la zona del pañal [ev_3].",
  "", `## ${p.doctor}`, "- Si tiene fiebre o la piel sangra o supura [ev_3].",
  "", `## ${p.remember}`, "- Una crema de barrera fina en cada cambio [ev_1].",
  "", `## ${p.mothers}`, "- Muchas lo dejan un rato sin pañal tras el baño [ex_1].",
].join("\n");

async function askDemo(page: Page) {
  await page.route("**/api/demo/ask", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ kind: "answer", intent: "plan", answer: planAnswer, evidence_citations: citations, disclaimer }),
  }));
  await page.goto("/es");
  await ask(page.locator("#demo-question"), "Tiene el culito muy rojo, ¿qué hago?", {
    send: page.getByRole("button", { name: "Preguntar", exact: true }),
  });
  await expect(page.getByTestId("demo-answer")).toBeVisible();
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: join(SHOTS, `${PHASE}-${name}.png`), style: "nextjs-portal { display: none !important; }" });
}

// What the eye sees in a cite: its CSS-drawn number (the model's marker stays
// in the DOM, hidden, so the text is untouched).
async function drawnNumber(cite: Locator): Promise<string> {
  return cite.evaluate((el) => getComputedStyle(el, "::before").content.replace(/^"|"$/g, ""));
}

async function noSideScroll(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test("demo: each marker is the number of its source card, and a tap opens that card", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  await askDemo(page);
  await shot(page, "demo-answer-390");

  const answer = page.getByTestId("answer-content");
  // The model's text is still there, verbatim.
  await expect(page.getByTestId("plan-intro")).toHaveText(
    "Es frecuente y suele poder tratarse en casa [ev_2]. Lo principal es que la piel quede limpia y seca [ev_1][ev_2].",
  );
  // What other mothers say is folded after a plan (2026-11-09): open it, so
  // its marker is read like every other one.
  await page.getByTestId("mothers-fold").locator(":scope > summary").click();
  const cites = answer.locator("[data-cite]");
  await expect(cites).toHaveCount(9);
  for (const cite of await cites.all()) {
    const key = (await cite.getAttribute("data-cite"))!;
    const n = key.replace(/^\D+_/, "");
    expect(await drawnNumber(cite)).toBe(n);
    await expect(cite).toHaveAccessibleName(`${es.questionnaire.sourceLabel} ${n}`);
    // Small, on the line: as a <button> the home page's 48 px button rule
    // made each one a tall pill that pushed the lines apart.
    expect((await cite.boundingBox())!.height).toBeLessThan(20);
  }

  // Every source card carries its number, the same one the text shows.
  const sources = page.getByTestId("answer-depth");
  for (const c of citations) {
    const card = sources.locator(`[data-cite-target="${c.tag}"]`);
    await expect(card).toHaveCount(1);
    await expect(card.getByTestId("source-number")).toHaveText(c.tag.split("_")[1]);
  }
  // Evidence and experience are drawn differently, in the text and on the card.
  const evClass = await answer.locator('[data-cite="ev_1"]').first().getAttribute("class");
  const exClass = await answer.locator('[data-cite="ex_1"]').getAttribute("class");
  expect(evClass).not.toBe(exClass);

  // Folded at first; a tap on "3" in "Cuándo ir al médico" opens the list and
  // the card, and brings it into view.
  await expect(sources).not.toHaveAttribute("open", "");
  const doctorCite = page.getByTestId("plan-section-doctor").locator('[data-cite="ev_3"]');
  await doctorCite.click();
  const card3 = sources.locator('[data-cite-target="ev_3"]');
  await expect(sources).toHaveAttribute("open", "");
  await expect(card3).toHaveAttribute("open", "");
  await expect(card3).toBeInViewport();
  await expect(card3.locator("summary")).toBeFocused();
  await shot(page, "demo-after-tap-390");
  await noSideScroll(page);

  // Keyboard: the marker is reachable and works like a button (Enter, Space).
  await page.getByTestId("plan-section-mothers").locator('[data-cite="ex_1"]').focus();
  await page.keyboard.press("Enter");
  await expect(sources.locator('[data-cite-target="ex_1"]')).toBeInViewport();
  await expect(sources.locator('[data-cite-target="ex_1"] summary')).toBeFocused();
  await page.getByTestId("plan-intro").locator('[data-cite="ev_2"]').first().focus();
  await page.keyboard.press(" ");
  await expect(sources.locator('[data-cite-target="ev_2"] summary')).toBeFocused();
  await expect(sources.locator('[data-cite-target="ev_2"]')).toHaveAttribute("open", "");

  // Nothing clinical is folded: only the source cards live in <details>.
  for (const key of ["today", "watch", "doctor", "remember"]) {
    expect(await page.getByTestId(`plan-section-${key}`).evaluate((el) => el.closest("details"))).toBeNull();
  }
  await expect(page.getByTestId("answer-disclaimer")).toBeVisible();

  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    const audit = await new AxeBuilder({ page }).include('[data-testid="demo-answer"]').analyze();
    expect(audit.violations, colorScheme).toEqual([]);
  }
  await page.getByTestId("plan-intro").scrollIntoViewIfNeeded();
  await shot(page, "demo-answer-390-dark");
});

function sse(events: [string, unknown][]): string {
  return events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

test("agent: a record marker matches its card in her history, drawn apart from evidence", async ({ browser }) => {
  const { cookie } = await seedUserAndSessionCookie(`e2e-cites-${Date.now()}@adelia.test`);
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  await context.addCookies([cookie]);
  const page = await context.newPage();
  await forceKeylessDemo(page);
  const text = "La última toma que anotaste fue a las 17:00 [1]. En la revisión le vieron la piel bien [2]. "
    + "Mantenerla limpia y seca es lo que más ayuda [ev_1].";
  await page.route("**/api/backend/agent/turn", (route: Route) => route.fulfill({
    status: 200, contentType: "text/event-stream",
    body: sse([["start", {}], ["token", { content: text }], ["final", {
      citations: [
        { chunk_id: "rc-1", document_id: "00000000-0000-0000-0000-000000000001", raw_quote: "Toma 17:00", page: null },
        { chunk_id: "rc-2", document_id: "00000000-0000-0000-0000-000000000002", raw_quote: "Revisión: piel normal", page: null },
      ],
      evidence_citations: [citations[0]],
    }]]),
  }));
  await page.goto("/es/dashboard");
  await ask(page.getByPlaceholder(es.agent.placeholder), "¿Cómo va la piel?");
  const answer = page.getByTestId("answer-content").last();
  await expect(answer).toContainText("lo que más ayuda");
  await shot(page, "agent-answer-390");

  await expect(answer).toHaveText(text);
  const rec2 = answer.locator('[data-cite="2"]');
  expect(await drawnNumber(rec2)).toBe("2");
  await expect(rec2).toHaveAccessibleName(`${es.dashboard.navHistory} 2`);
  await expect(answer.locator('[data-cite="ev_1"]')).toHaveAccessibleName(`${es.questionnaire.sourceLabel} 1`);
  expect(await rec2.getAttribute("class")).not.toBe(await answer.locator('[data-cite="ev_1"]').getAttribute("class"));

  const recordCard = page.locator('[data-cite-target="rec_2"]');
  await expect(recordCard.getByTestId("source-number")).toHaveText("2");
  await expect(page.locator('[data-cite-target="rec_1"]').getByTestId("source-number")).toHaveText("1");
  await expect(page.locator('[data-cite-target="ev_1"]').getByTestId("source-number")).toHaveText("1");
  await rec2.click();
  await expect(recordCard).toBeFocused();
  await expect(recordCard).toBeInViewport();
  await shot(page, "agent-after-tap-390");
  await noSideScroll(page);

  const audit = await new AxeBuilder({ page }).include("main").analyze();
  expect(audit.violations).toEqual([]);
  await context.close();
});
