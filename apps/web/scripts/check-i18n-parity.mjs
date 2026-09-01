#!/usr/bin/env node
// Leaf-key parity across es / en / fr, plus the French typography rules the
// product commits to.
//
// The catalogues were verified by hand in the audit ("857 claves idénticas en
// es, en y fr, sin una sola ausencia ni sobra"), which is exactly the kind of
// invariant that holds until the day it does not: next-intl renders a missing
// key as the key itself, so a French mother reads "onboarding.dobHint" on a
// medical form and nothing fails anywhere else.
//
// Fatal:
//   1. the three catalogues have the same set of LEAF paths (a namespace that
//      is an object in one file and a string in another is a mismatch too);
//   2. a key that is empty in one language and translated in another (an
//      intentional blank, like the corner cell of the comparison table, is
//      empty in all three and is not a gap).
//
// Reported but not fatal:
//   3. French of France: U+00A0 before : ; ? ! and the typographic apostrophe
//      U+2019, never the straight one. This is pre-existing debt across the
//      older namespaces, being burnt down namespace by namespace, so it is
//      surfaced with an exact count rather than used to block a build it did
//      not break. New strings must not add to the count.
//
// Run: node scripts/check-i18n-parity.mjs

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const messagesDir = join(here, "..", "messages");
const LOCALES = ["es", "en", "fr"];

function leaves(value, prefix, out) {
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (child !== null && typeof child === "object" && !Array.isArray(child)) {
      leaves(child, path, out);
    } else {
      out.set(path, child);
    }
  }
  return out;
}

const catalogues = new Map();
for (const locale of LOCALES) {
  const raw = readFileSync(join(messagesDir, `${locale}.json`), "utf8");
  catalogues.set(locale, leaves(JSON.parse(raw), "", new Map()));
}

const problems = [];

// 1. parity, measured against the union so a key missing everywhere but one
//    is reported once per catalogue that lacks it.
const union = new Set();
for (const map of catalogues.values()) for (const key of map.keys()) union.add(key);
for (const locale of LOCALES) {
  const map = catalogues.get(locale);
  for (const key of union) {
    if (!map.has(key)) problems.push(`${locale}: missing key ${key}`);
  }
}

// 2. a gap, not a deliberate blank: empty here and translated there
for (const key of union) {
  const empties = LOCALES.filter((l) => {
    const value = catalogues.get(l).get(key);
    return typeof value === "string" && value.trim() === "";
  });
  if (empties.length > 0 && empties.length < LOCALES.length) {
    problems.push(`empty in ${empties.join(", ")} but translated elsewhere: ${key}`);
  }
}

// 3. French typography. The straight apostrophe and a plain space before a
//    double punctuation mark are the two mistakes that make a French page
//    read as machine-translated.
//    ICU placeholders ({name}, plural forms) legitimately carry braces, so
//    only the characters outside them are inspected for the space rule.
const typography = [];
for (const [key, value] of catalogues.get("fr")) {
  if (typeof value !== "string") continue;
  if (value.includes("'")) {
    typography.push(`${key}: straight apostrophe (use ’)`);
  }
  const withoutIcu = value.replace(/\{[^{}]*\}/g, "");
  for (const mark of [":", ";", "?", "!"]) {
    const index = withoutIcu.indexOf(mark);
    if (index > 0 && withoutIcu[index - 1] === " ") {
      typography.push(`${key}: plain space before "${mark}" (use U+00A0)`);
    }
  }
}
const counts = LOCALES.map((l) => `${l}=${catalogues.get(l).size}`).join(" ");
if (problems.length > 0) {
  console.error(`i18n parity FAILED (${counts})`);
  for (const problem of problems.slice(0, 50)) console.error(`  - ${problem}`);
  if (problems.length > 50) console.error(`  ... and ${problems.length - 50} more`);
  process.exit(1);
}
console.log(`i18n parity OK: ${counts} leaf keys`);
if (typography.length > 0) {
  console.log(
    `French typography debt: ${typography.length} string(s) still to convert ` +
      `(straight apostrophes / plain space before : ; ? !).`,
  );
  for (const item of typography.slice(0, 10)) console.log(`  · ${item}`);
  if (typography.length > 10) {
    console.log(`  · ... and ${typography.length - 10} more`);
  }
} else {
  console.log("French typography clean");
}
