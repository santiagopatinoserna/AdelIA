import { expect, test } from "@playwright/test";

import { askExampleKey } from "@/lib/ask-example";
import en from "../messages/en.json";
import es from "../messages/es.json";
import fr from "../messages/fr.json";

// The "Pregunta con citas" example follows the age of the child on screen
// (seen in production on 2026-11-06: Lucía, 5 months, was offered "¿Es normal
// que con 13 meses solo quiera leche materna?", which read as a template).
// Pure checks, no server: the band each age falls into, and that no example
// names an age other than the child's own.

const CATALOGS = { es, en, fr } as const;
type Catalog = (typeof CATALOGS)[keyof typeof CATALOGS];

function example(catalog: Catalog, months: number | null): string {
  return catalog.showcaseAsk[askExampleKey(months)];
}

// Any "13 meses", "13-month-old", "13 mois", "1 an", "2 years" in the text.
const AGE_IN_TEXT =
  /(\d+)\s*(?:-\s*)?(meses|mes|months?|mois|semanas|weeks?|semaines?|años?|years?|ans?)\b/giu;

function agesNamed(text: string): string[] {
  return [...text.matchAll(AGE_IN_TEXT)].map((m) => m[0]);
}

test("every age from birth to 24 months gets an example, and no age gets another age's", () => {
  for (let months = 0; months <= 24; months++) {
    for (const [locale, catalog] of Object.entries(CATALOGS)) {
      const text = example(catalog, months);
      expect(text, `${locale} at ${months} months`).toBeTruthy();
      expect(agesNamed(text), `${locale} at ${months} months: "${text}"`).toEqual([]);
    }
  }
});

test("Lucía at 5 months and a child of 20 months are offered different, fitting questions", () => {
  expect(askExampleKey(5)).toBe("young");
  expect(askExampleKey(20)).toBe("toddler");
  // The 13-month sentence that started this is a toddler question: it must
  // never reach a 5-month-old again, in any locale.
  expect(es.showcaseAsk.young).not.toContain("leche materna");
  expect(es.showcaseAsk.young).toContain("toma");
  expect(es.showcaseAsk.toddler).toContain("leche materna");
});

test("the bands meet at the ages a parent's questions change", () => {
  expect(askExampleKey(0)).toBe("young");
  expect(askExampleKey(5)).toBe("young");
  expect(askExampleKey(6)).toBe("solids");
  expect(askExampleKey(11)).toBe("solids");
  expect(askExampleKey(12)).toBe("toddler");
  expect(askExampleKey(24)).toBe("toddler");
  // No birth date, or a profile past the product's range (her own row): an
  // example that fits any age, never a guess.
  expect(askExampleKey(null)).toBe("noAge");
  expect(askExampleKey(25)).toBe("noAge");
  expect(askExampleKey(400)).toBe("noAge");
});

test("the four examples are distinct in every locale and the catalogs share their keys", () => {
  for (const catalog of Object.values(CATALOGS)) {
    const texts = Object.values(catalog.showcaseAsk);
    expect(new Set(texts).size).toBe(texts.length);
  }
  expect(Object.keys(en.showcaseAsk).sort()).toEqual(Object.keys(es.showcaseAsk).sort());
  expect(Object.keys(fr.showcaseAsk).sort()).toEqual(Object.keys(es.showcaseAsk).sort());
});
