import { expect, test } from "@playwright/test";

import budgets from "./budgets.json";
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
  openContext,
  record,
  screenIssues,
  settle,
  shot,
} from "./page";

// The landing (first visit, no session, cookie banner and all) and the panel
// of the battery's guest before any question, at every width, scheme and
// language: the first-screen budget, covered controls, sideways scrolling,
// 44 px targets (the folded "Más" opened too) and the keyboard over the field.

const BUDGETS = budgets as Record<string, FirstScreen>;

function budgetIssues(key: string, measured: FirstScreen): Issue[] {
  return overBudget(measured, BUDGETS[key], key).map((detail) => ({ kind: "budget" as const, where: key, detail }));
}

for (const v of VIEWPORTS) {
  for (const locale of LOCALES) {
    for (const scheme of SCHEMES) {
      const tag = `${v.name}.${locale}.${scheme}`;

      test(`10.${tag} Portada, primera visita`, async ({ browser, baseURL }) => {
        const { context, page, guard, errors } = await openContext(browser, {
          viewport: v, scheme, locale, guest: false, baseURL: baseURL!,
        });
        try {
          await page.goto(`/${locale}`);
          await settle(page);
          const where = `landing.${tag}`;
          const fs = await firstScreen(page);
          record({ type: "metric", section: "first-screen", key: `landing.${tag}`, values: { ...fs } });
          await shot(page, `10-landing-${v.name}-${locale}-${scheme}`);
          const found = [
            ...budgetIssues(budgetKey("landing", v, locale), fs),
            ...(await screenIssues(page, where)),
          ];
          const kb = await keyboardProblems(
            page, "#demo-question", v, KEYBOARD_HEIGHT(v), [],
            scheme === "light" ? `10-landing-${v.name}-${locale}-keyboard` : undefined,
          );
          found.push(...kb.map((detail) => ({ kind: "keyboard-covers" as const, where, detail })));
          found.push(...errorIssues(errors, where));
          issues(found);
          expect.soft(guard.modelRequests, "answering-path requests").toEqual([]);
          expect(found, where).toEqual([]);
        } finally {
          await context.close();
        }
      });

      test(`11.${tag} Panel de la invitada, sin preguntar`, async ({ browser, baseURL }) => {
        needGuest();
        const { context, page, guard, errors } = await openContext(browser, {
          viewport: v, scheme, locale, guest: true, baseURL: baseURL!,
        });
        try {
          await page.goto(`/${locale}/dashboard`);
          await expect(page.getByTestId("today-card")).toBeVisible();
          await settle(page);
          const where = `panel.${tag}`;
          const fs = await firstScreen(page);
          record({ type: "metric", section: "first-screen", key: `panel.${tag}`, values: { ...fs } });
          await shot(page, `11-panel-${v.name}-${locale}-${scheme}`);
          const found = [
            ...budgetIssues(budgetKey("panel", v, locale), fs),
            ...(await screenIssues(page, where)),
          ];
          // Everything under "Más" is pressed with the same thumb.
          await page.getByTestId("panel-more").locator(":scope > summary").click();
          await settle(page);
          // Only what opening it adds: the header is the same one.
          const seen = new Set(found.map((i) => i.detail));
          found.push(...(await screenIssues(page, `${where}.mas`)).filter((i) => !seen.has(i.detail)));
          await page.getByTestId("panel-more").locator(":scope > summary").click();
          const kb = await keyboardProblems(
            page, "[data-testid=agent-canvas] textarea", v, KEYBOARD_HEIGHT(v),
            ["[data-testid=agent-canvas] .ad-btn-primary"],
            scheme === "light" ? `11-panel-${v.name}-${locale}-keyboard` : undefined,
          );
          found.push(...kb.map((detail) => ({ kind: "keyboard-covers" as const, where, detail })));
          found.push(...errorIssues(errors, where));
          issues(found);
          expect.soft(guard.violations, "requests the model guard stopped").toEqual([]);
          expect(found, where).toEqual([]);
        } finally {
          await context.close();
        }
      });
    }
  }
}
