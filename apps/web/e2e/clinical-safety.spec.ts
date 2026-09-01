import { expect, test } from "@playwright/test";

import esMessages from "@/messages/es.json";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { seedUserAndSessionCookie } from "./utils/session";

/**
 * The fixed clinical disclaimer (audit 3.8).
 *
 * It used to be a clause in the system prompt, so it appeared only when the
 * model chose to obey: never on a refusal, never on a red-flag referral, and
 * never at all on the agent canvas, which is the screen a parent lands on.
 * The interface paints it now, on both answering surfaces, in all three
 * languages, anchored to the composer so it needs no scrolling.
 */

const CATALOGS = { es: esMessages, en: enMessages, fr: frMessages } as const;

for (const [locale, messages] of Object.entries(CATALOGS)) {
  test(`the ${locale} catalogue carries the clinical disclaimer`, () => {
    const text = (messages as any).common.clinicalDisclaimer as string;
    expect(text).toBeTruthy();
    expect(text).not.toContain("—"); // no em dashes in user-facing text
    expect(text.toLowerCase()).toMatch(/pediatra|pediatrician|pédiatre/);
  });

  test(`the ${locale} agent canvas can label both citation blocks`, () => {
    expect((messages as any).agent.citationSourceEvidence).toBeTruthy();
    expect((messages as any).agent.citationSourceUserData).toBeTruthy();
  });
}

test("the disclaimer wording is identical to the API's canonical copy", () => {
  // apps/api/adelia/services/answer_contract.py holds the same three strings,
  // so a change on one side that is not made on the other is a visible drift
  // rather than a silent one.
  expect(esMessages.common.clinicalDisclaimer).toBe(
    "AdelIA no sustituye a tu pediatra. Verifica con tu médico antes de tomar decisiones clínicas.",
  );
  expect(enMessages.common.clinicalDisclaimer).toBe(
    "AdelIA does not replace your pediatrician. Verify with your doctor before making clinical decisions.",
  );
  expect(frMessages.common.clinicalDisclaimer).toBe(
    "AdelIA ne remplace pas votre pédiatre. Vérifiez avec votre médecin avant toute décision clinique.",
  );
});

test("French keeps its non-breaking spaces on the answering surfaces", () => {
  // Repo rule: French of France puts U+00A0 before : ; ? ! . The scope here
  // is the two surfaces that answer a parent (chat, agent) plus the shared
  // strings they use; the rest of the catalogue still has offenders and is
  // tracked separately, so this guard is honest about what it covers.
  const NBSP = "\u00a0";
  const offenders: string[] = [];
  const walk = (node: unknown, path: string) => {
    if (typeof node === "string") {
      if (node.includes("http")) return;
      for (const match of node.matchAll(/(.)([:;?!])/g)) {
        const [, before, punct] = match;
        if (before === NBSP) continue;
        if (punct === ":" && /\d/.test(before)) continue; // 08:50 is a time
        offenders.push(`${path}: ${node}`);
        break;
      }
      return;
    }
    if (node && typeof node === "object") {
      for (const [k, v] of Object.entries(node)) walk(v, `${path}.${k}`);
    }
  };
  walk(frMessages.chat, "chat");
  walk(frMessages.agent, "agent");
  walk(frMessages.common.clinicalDisclaimer, "common.clinicalDisclaimer");
  walk(frMessages.common.errorId, "common.errorId");
  expect(offenders).toEqual([]);
});

test("French uses the typographic apostrophe on the answering surfaces", () => {
  const straight: string[] = [];
  const walk = (node: unknown, path: string) => {
    if (typeof node === "string") {
      if (node.includes("'")) straight.push(`${path}: ${node}`);
      return;
    }
    if (node && typeof node === "object") {
      for (const [k, v] of Object.entries(node)) walk(v, `${path}.${k}`);
    }
  };
  walk(frMessages.chat, "chat");
  walk(frMessages.agent, "agent");
  expect(straight).toEqual([]);
});

// ---------------------------------------------------------------------------
// And the same disclaimer really is on screen, on both surfaces, in the three
// languages, without scrolling. The catalogue tests above prove the strings
// exist; these prove they are painted.
// ---------------------------------------------------------------------------


const SURFACES = [
  ["/dashboard", "agent canvas"],
  ["/dashboard/chat", "chat"],
] as const;

for (const [path, surface] of SURFACES) {
  for (const locale of ["es", "en", "fr"] as const) {
    test(`the clinical disclaimer is visible without scrolling on the ${surface} in ${locale}`, async ({
      browser,
    }) => {
      const { cookie } = await seedUserAndSessionCookie(
        `e2e-disclaimer-${locale}-${surface.replace(/\s/g, "")}-${Date.now()}@adelia.test`,
      );
      const context = await browser.newContext();
      await context.addCookies([cookie]);
      const page = await context.newPage();
      await page.goto(`/${locale}${path}`);

      const disclaimer = page.getByTestId("clinical-disclaimer");
      await expect(disclaimer).toBeVisible();
      await expect(disclaimer).toContainText(
        (CATALOGS[locale] as any).common.clinicalDisclaimer,
      );

      // "Without scrolling" is the criterion the audit wrote, so measure it:
      // the element's box has to sit inside the viewport as loaded.
      const box = await disclaimer.boundingBox();
      const viewport = page.viewportSize();
      expect(box).not.toBeNull();
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height + 1);

      await context.close();
    });
  }
}
