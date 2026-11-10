import { type Page, expect, test } from "@playwright/test";

import budgets from "./budgets.json";
import { URGENT_QUESTIONS } from "../kit";
import {
  KEYBOARD_HEIGHT,
  LOCALES,
  SCHEMES,
  VIEWPORTS,
  type FirstScreen,
  type Issue,
  budgetKey,
  overBudget,
} from "./kit";
import {
  errorIssues,
  firstScreen,
  issues,
  keyboardProblems,
  needGuest,
  note,
  openContext,
  record,
  screenIssues,
  settle,
  shot,
} from "./page";

// The battery guest's conversation: two red flags, answered in code by the
// guard before any model (the smoke suite's questions), so every later check
// can open a real thread. Then, at every width, scheme and language, the
// thread as she finds it after a reload: one tap on «Seguir la conversación»,
// the urgency still on the first screen, nothing covered, the keyboard.

const [FIRST, SECOND] = URGENT_QUESTIONS;
const BUDGETS = budgets as Record<string, FirstScreen>;

/** The 112 of an urgent answer, on the screen she is looking at. */
async function urgencyInView(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const answers = [...document.querySelectorAll('[data-role="assistant"] [data-testid="answer-content"]')];
    return answers.some((a) => {
      const walker = document.createTreeWalker(a, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (!(n.textContent || "").includes("112")) continue;
        const range = document.createRange();
        range.selectNodeContents(n);
        const r = range.getBoundingClientRect();
        if (r.top >= 0 && r.bottom <= innerHeight && r.height > 0) return true;
      }
      return false;
    });
  });
}

test("20 Hilo de la invitada: dos urgencias, la respuesta empieza en pantalla", async ({ browser, baseURL }) => {
  needGuest();
  const v = VIEWPORTS[1];
  const { context, page, guard, errors } = await openContext(browser, {
    viewport: v, scheme: "light", locale: "es", guest: true, baseURL: baseURL!,
  });
  try {
    await page.goto("/es/dashboard");
    const field = page.getByTestId("agent-canvas").locator("textarea");
    const answers = page.locator('[data-role="assistant"]');
    const found: Issue[] = [];

    for (const [n, question] of [FIRST, SECOND].entries()) {
      await field.fill(question);
      await field.press("Enter");
      await expect(answers.nth(n)).toContainText("112", { timeout: 30_000 });
      await settle(page);
      // She reads from the first line: the urgency is on screen, without
      // scrolling, as soon as it arrives (UX_PRINCIPLES 13 and 15).
      if (!(await urgencyInView(page)))
        found.push({ kind: "safety-hidden", where: `answer.urgent.390.es.${n + 1}`, detail: "el 112 de la urgencia no está en la pantalla al llegar la respuesta" });
      // UX_PRINCIPLES 13: the urgency opens with «Llamar al 112» in one tap,
      // as the demo's urgent block does (call-emergency, a tel: link).
      if ((await answers.nth(n).locator('a[href^="tel:"]').count()) === 0)
        found.push({ kind: "urgent-no-call", where: `answer.urgent.390.es.${n + 1}`, detail: "la urgencia del panel dice «Llama al 112» como texto, sin botón para llamar" });
      await shot(page, `20-urgent-${n + 1}-390-es`);
    }
    found.push(...errorIssues(errors, "thread.390.es"));
    issues(found);
    expect(guard.turns, "two red-flag turns, nothing else").toHaveLength(2);
    expect(guard.violations).toEqual([]);
    expect(found).toEqual([]);
    note("2 red flags answered in code; thread stored for 21");
  } finally {
    await context.close();
  }
});

for (const v of VIEWPORTS) {
  for (const locale of LOCALES) {
    for (const scheme of SCHEMES) {
      const tag = `${v.name}.${locale}.${scheme}`;

      test(`21.${tag} Hilo empezado, tras recargar`, async ({ browser, baseURL }) => {
        needGuest();
        const { context, page, guard, errors } = await openContext(browser, {
          viewport: v, scheme, locale, guest: true, baseURL: baseURL!,
        });
        try {
          await page.goto(`/${locale}/dashboard`);
          const resume = page.getByTestId("continue-conversation");
          await expect(resume, "«Seguir la conversación» on the first screen").toBeInViewport();
          await resume.click();
          await expect(page.getByTestId("agent-message")).toHaveCount(4);
          await settle(page);
          const where = `thread.${tag}`;
          const fs = await firstScreen(page);
          record({ type: "metric", section: "first-screen", key: where, values: { ...fs } });
          await shot(page, `21-thread-${v.name}-${locale}-${scheme}`);
          const key = budgetKey("thread", v, locale);
          const found: Issue[] = [
            ...overBudget(fs, BUDGETS[key], key).map((detail) => ({ kind: "budget" as const, where: key, detail })),
            ...(await screenIssues(page, where)),
          ];
          if (!(await urgencyInView(page)))
            found.push({ kind: "safety-hidden", where, detail: "al seguir la conversación no se ve ningún 112 en la primera pantalla" });
          const kb = await keyboardProblems(
            page, "[data-testid=agent-canvas] textarea", v, KEYBOARD_HEIGHT(v),
            ["[data-testid=agent-canvas] .ad-btn-primary"],
            scheme === "light" ? `21-thread-${v.name}-${locale}-keyboard` : undefined,
          );
          found.push(...kb.map((detail) => ({ kind: "keyboard-covers" as const, where, detail })));
          found.push(...errorIssues(errors, where));
          issues(found);
          expect.soft(guard.turns, "no turn sent by resuming").toEqual([]);
          expect(found, where).toEqual([]);
        } finally {
          await context.close();
        }
      });
    }
  }
}
