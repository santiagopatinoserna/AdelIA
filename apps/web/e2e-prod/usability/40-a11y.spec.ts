import { expect, test } from "@playwright/test";

import { LOCALES, SCHEMES, VIEWPORTS, type Issue } from "./kit";
import { axeBlocking, issues, needGuest, openContext, record } from "./page";

// axe on what a mother opens, at 390 px, light and dark, es/en/fr: the
// landing, the guest's panel, Settings, Privacy and a real answer (the
// guard's urgency, resumed from the battery guest's thread). Serious and
// critical violations fail; the plan is read by 30 at the same width.

const PAGES = [
  { name: "portada", path: "", guest: false },
  { name: "panel", path: "/dashboard", guest: true },
  { name: "ajustes", path: "/dashboard/settings", guest: true },
  { name: "privacidad", path: "/privacidad", guest: false },
  { name: "urgencia", path: "/dashboard", guest: true, resume: true },
] as const;

for (const locale of LOCALES) {
  for (const scheme of SCHEMES) {
    test(`40.${locale}.${scheme} Accesibilidad (axe)`, async ({ browser, baseURL }) => {
      needGuest();
      const found: Issue[] = [];
      for (const p of PAGES) {
        const { context, page } = await openContext(browser, {
          viewport: VIEWPORTS[1], scheme, locale, guest: p.guest, baseURL: baseURL!,
        });
        try {
          await page.goto(`/${locale}${p.path}`);
          if ("resume" in p) {
            await page.getByTestId("continue-conversation").click();
            await expect(page.getByTestId("agent-message")).toHaveCount(4);
          }
          const blocking = await axeBlocking(page);
          const where = `${p.name}.${locale}.${scheme}`;
          record({
            type: "metric", section: "a11y", key: where,
            values: { serio_o_critico: blocking.length, reglas: blocking.map((b) => `${b.id} (${b.nodes})`).join(" ") },
          });
          found.push(...blocking.map((b) => ({ kind: "a11y" as const, where, detail: `${b.id}: ${b.help}` })));
        } finally {
          await context.close();
        }
      }
      issues(found);
      expect(found).toEqual([]);
    });
  }
}
