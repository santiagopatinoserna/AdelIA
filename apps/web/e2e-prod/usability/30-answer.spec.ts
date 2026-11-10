import { type Locator, type Page, expect, test } from "@playwright/test";

import fixtures from "./fixtures.json";
import { LOCALES, SCHEMES, VIEWPORTS, type Issue, type Viewport } from "./kit";
import {
  axeBlocking,
  errorIssues,
  issues,
  needGuest,
  note,
  openContext,
  record,
  screenIssues,
  settle,
  shot,
} from "./page";

// A plan and a two-question clarify card in the battery guest's panel, at
// every width, scheme and language. Both are answered inside the browser
// from fixtures.json (kit.stubTurnFor): no model, no request leaves. What is
// measured is the page, not the advice: the plan opens with its sentence and
// «Hoy» on the first screen, the jump to «Cuándo ir al médico» is there too
// and lands on an open section, the disclaimer stays; the card is answered
// with two taps of a thumb. axe reads the plan at 390 px.

type Box = { top: number; bottom: number; height: number; vh: number; left: number; right: number };

async function box(l: Locator): Promise<Box | null> {
  if ((await l.count()) === 0) return null;
  return l.first().evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { top: r.top, bottom: r.bottom, height: r.height, vh: innerHeight, left: r.left, right: r.right };
  });
}

const inView = (b: Box | null) => !!b && b.height > 0 && b.top >= -0.5 && b.bottom <= b.vh + 0.5;

async function send(page: Page, text: string) {
  const field = page.getByTestId("agent-canvas").locator("textarea");
  await field.fill(text);
  await field.press("Enter");
}

async function planChecks(page: Page, where: string): Promise<Issue[]> {
  const out: Issue[] = [];
  const answer = page.locator('[data-role="assistant"]').last();
  const intro = answer.getByTestId("plan-intro");
  const today = answer.getByTestId("plan-section-today");
  const jump = answer.getByTestId("plan-map").getByRole("button");
  const doctor = answer.getByTestId("plan-section-doctor");
  const ib = await box(intro);
  const tb = await box(today.getByRole("heading"));
  if (!ib || ib.top < -0.5 || ib.top > ib.vh * 0.6)
    out.push({ kind: "reading-order", where, detail: "la frase inicial del plan no empieza en la primera pantalla" });
  if (!inView(tb)) out.push({ kind: "reading-order", where, detail: "«Hoy» no está en la primera pantalla" });
  // Between the opening and «Hoy» only the jump to the doctor fits.
  const order = await answer.getByTestId("answer-content").evaluate((el) =>
    [...el.children].map((c) => c.getAttribute("data-testid") ?? c.tagName.toLowerCase()),
  );
  if (order.slice(0, 3).join(",") !== "plan-intro,plan-map,plan-section-today")
    out.push({ kind: "reading-order", where, detail: `orden del plan: ${order.slice(0, 3).join(", ")}` });
  if (!inView(await box(jump)))
    out.push({ kind: "safety-hidden", where, detail: "el salto a «Cuándo ir al médico» no está en la primera pantalla" });
  const folded = await doctor.evaluate((el) => !!el.closest("details:not([open])")).catch(() => true);
  if (folded || !(await doctor.isVisible()))
    out.push({ kind: "safety-hidden", where, detail: "«Cuándo ir al médico» está plegado o no se ve" });
  if (!inView(await box(page.getByTestId("clinical-disclaimer"))))
    out.push({ kind: "safety-hidden", where, detail: "el descargo no se ve con la respuesta" });
  out.push(...(await screenIssues(page, where)));
  // One tap takes her to it, open.
  if (await jump.isVisible()) {
    await jump.click();
    await page.waitForTimeout(900);
    if (!inView(await box(doctor.getByRole("heading"))))
      out.push({ kind: "safety-hidden", where, detail: "tras el salto, «Cuándo ir al médico» no queda en pantalla" });
  }
  return out;
}

async function clarifyChecks(page: Page, v: Viewport, where: string, stubbed: Record<string, unknown>[]): Promise<{ found: Issue[]; fit: string }> {
  const out: Issue[] = [];
  const card = page.getByTestId("clarify-card");
  await expect(card).toBeVisible({ timeout: 15_000 });
  await settle(page);
  const cb = (await box(card))!;
  const groups = card.getByRole("group");
  const buttons = card.locator("[data-testid=clarify-option], [data-testid=clarify-skip]");
  const n = await buttons.count();
  let inThumb = 0;
  let onScreen = 0;
  for (let i = 0; i < n; i++) {
    const b = buttons.nth(i);
    const label = (await b.innerText()).trim();
    const bb = (await box(b))!;
    if (bb.height < 44 - 0.05) out.push({ kind: "clarify-thumb", where, detail: `«${label}» mide ${bb.height.toFixed(0)} px de alto` });
    if ((await b.getAttribute("data-testid")) === "clarify-option" && bb.right - bb.left < (cb.right - cb.left) * 0.6)
      out.push({ kind: "clarify-thumb", where, detail: `«${label}» no ocupa el ancho de la tarjeta` });
    if (inView(bb)) onScreen++;
    // The top quarter of a phone is out of a thumb's reach.
    if ((bb.top + bb.bottom) / 2 > bb.vh * 0.25) inThumb++;
  }
  const firstGroup = groups.first().locator("button");
  for (let i = 0; i < (await firstGroup.count()); i++) {
    if (!inView(await box(firstGroup.nth(i)))) {
      out.push({ kind: "clarify-thumb", where, detail: "la primera pregunta no cabe entera en la pantalla al llegar" });
      break;
    }
  }
  if (onScreen < n) out.push({ kind: "clarify-thumb", where, detail: "hay que desplazarse para ver todas las respuestas de la tarjeta" });
  if (v.phone && inThumb < n) out.push({ kind: "clarify-thumb", where, detail: "hay botones de la tarjeta fuera del alcance del pulgar (arriba del todo)" });
  const free = card.locator("p").last();
  if (!inView(await box(free))) out.push({ kind: "clarify-thumb", where, detail: "«O escríbemelo» no se ve sin desplazarse" });
  out.push(...(await screenIssues(page, where)));
  await shot(page, `30-clarify-${where.replace(/^clarify\./, "").replace(/\./g, "-")}`);

  // Two taps, one per question, and the turn goes.
  const before = stubbed.length;
  await groups.nth(0).getByTestId("clarify-option").first().click();
  await groups.nth(1).getByTestId("clarify-option").first().click();
  await expect(page.getByTestId("plan-section-today")).toBeVisible({ timeout: 15_000 });
  const sent = stubbed.slice(before);
  const answers = (sent[0]?.clarifications as unknown[] | undefined) ?? [];
  if (sent.length !== 1 || answers.length !== 2)
    out.push({ kind: "clarify-thumb", where, detail: `dos toques mandan ${sent.length} turnos con ${answers.length} respuestas` });
  return { found: out, fit: `${onScreen}/${n} en pantalla, ${inThumb}/${n} al alcance del pulgar` };
}

for (const v of VIEWPORTS) {
  for (const locale of LOCALES) {
    for (const scheme of SCHEMES) {
      const tag = `${v.name}.${locale}.${scheme}`;

      test(`30.${tag} Plan y tarjeta de aclaración (simulados)`, async ({ browser, baseURL }) => {
        needGuest();
        const { context, page, guard, stubbed, errors } = await openContext(browser, {
          viewport: v, scheme, locale, guest: true, baseURL: baseURL!,
        });
        try {
          await page.goto(`/${locale}/dashboard`);
          await expect(page.getByTestId("today-card")).toBeVisible();
          await send(page, fixtures.plan[locale].message);
          await expect(page.getByTestId("plan-section-today")).toBeVisible({ timeout: 15_000 });
          await settle(page);
          await shot(page, `30-plan-${v.name}-${locale}-${scheme}`);
          const found = await planChecks(page, `plan.${tag}`);
          if (v.name === "390") {
            const axe = await axeBlocking(page);
            record({ type: "metric", section: "a11y", key: `plan.${locale}.${scheme}`, values: { serio_o_critico: axe.length, reglas: axe.map((a) => a.id).join(" ") } });
            found.push(...axe.map((a) => ({ kind: "a11y" as const, where: `plan.${locale}.${scheme}`, detail: `${a.id}: ${a.help}` })));
          }

          await page.getByTestId("new-conversation").click();
          await send(page, fixtures.clarify[locale].message);
          const clarify = await clarifyChecks(page, v, `clarify.${tag}`, stubbed);
          found.push(...clarify.found);
          record({ type: "metric", section: "clarify", key: tag, values: { botones: clarify.fit } });
          found.push(...errorIssues(errors, `answer.${tag}`));
          issues(found);
          expect.soft(guard.turns, "no turn reached the API").toEqual([]);
          expect.soft(guard.violations, "no unstubbed turn").toEqual([]);
          expect(found, tag).toEqual([]);
          note(`plan + clarify simulated in the browser; ${clarify.fit}`);
        } finally {
          await context.close();
        }
      });
    }
  }
}
