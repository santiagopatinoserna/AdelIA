// The dark scheme is declared twice in app/globals.css: once under
// `@media (prefers-color-scheme: dark)` (the system preference) and once under
// `:root[data-theme="dark"]` (the future switcher). A token added to one and
// forgotten in the other is invisible until someone flips the switch, so this
// script compares the two declaration lists and fails if they drift.
//   node scripts/check-dark-tokens.mjs
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const blocks = [
  ...css.matchAll(
    /(?::root:not\(\[data-theme="light"\]\)|:root\[data-theme="dark"\])\s*\{([^}]*)\}/g,
  ),
]
  .map((m) => m[1])
  .filter((b) => b.includes("--color-canvas"));

if (blocks.length !== 2) {
  console.error(`FAIL: expected 2 dark blocks declaring --color-canvas, found ${blocks.length}`);
  process.exit(1);
}
const sets = blocks.map((b) => new Set([...b.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1])));
const values = blocks.map(
  (b) => new Map([...b.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()])),
);
const onlyA = [...sets[0]].filter((k) => !sets[1].has(k));
const onlyB = [...sets[1]].filter((k) => !sets[0].has(k));
const differing = [...values[0]].filter(([k, v]) => values[1].has(k) && values[1].get(k) !== v);
if (onlyA.length || onlyB.length || differing.length) {
  console.error("FAIL: the two dark blocks are out of sync");
  if (onlyA.length) console.error("  only in the media-query block:", onlyA.join(", "));
  if (onlyB.length) console.error("  only in the data-theme block:", onlyB.join(", "));
  for (const [k, v] of differing) console.error(`  different value for ${k}: ${v} vs ${values[1].get(k)}`);
  process.exit(1);
}
console.log(`dark blocks in sync, ${sets[0].size} tokens`);
