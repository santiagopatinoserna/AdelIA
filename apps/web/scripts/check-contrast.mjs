// WCAG 2.1 contrast of every role pair the design system actually renders,
// computed (not remembered) from the hex values in app/globals.css, in BOTH
// schemes. Text needs 4.5:1; borders, icons and component boundaries need
// 3.0:1 (WCAG 1.4.11). The focus ring is two-tone, so it passes when EITHER
// tone clears 3.0:1 against the ground it lands on.
//   node scripts/check-contrast.mjs
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

function tokensOf(body) {
  return new Map(
    [...body.matchAll(/(--color-[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)].map((m) => [m[1], m[2]]),
  );
}
const themeBody = css.match(/@theme static\s*\{([\s\S]*?)\n\}/)[1];
const light = tokensOf(themeBody);
// Anchor on the block that actually DECLARES the palette, not on the first
// `:root[data-theme="dark"] {` in the file: the one-liner that only sets
// `color-scheme: dark` closes on its own line, so a lazy `[\s\S]*?\n\}` ran
// straight past it and captured the @media block instead: this script was
// measuring the media-query palette twice and never reading the switcher's.
// `[^}]*` cannot cross the one-liner, and requiring --color-canvas skips it.
const darkBody = [...css.matchAll(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/g)]
  .map((m) => m[1])
  .find((b) => b.includes("--color-canvas"));
if (!darkBody) {
  console.error('FAIL: no :root[data-theme="dark"] palette block found in globals.css');
  process.exit(1);
}
const dark = new Map([...light, ...tokensOf(darkBody)]);

const srgb = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => srgb(parseInt(hex.slice(i, i + 2), 16) / 255));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function ratio(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const TEXT = 4.5;
const NON_TEXT = 3.0;

// [foreground, background, threshold]
const PAIRS = [
  ["ink", "canvas", TEXT], ["ink", "surface", TEXT], ["ink", "surface-2", TEXT], ["ink", "surface-3", TEXT],
  ["ink-soft", "canvas", TEXT], ["ink-soft", "surface", TEXT], ["ink-soft", "surface-2", TEXT],
  ["ink-soft", "surface-3", TEXT], ["ink-soft", "primary-tint", TEXT],
  ["ink-faint", "canvas", TEXT], ["ink-faint", "surface", TEXT], ["ink-faint", "surface-2", TEXT],
  ["ink-faint", "surface-3", TEXT],
  ["primary-text", "canvas", TEXT], ["primary-text", "surface", TEXT],
  ["primary-text", "surface-2", TEXT], ["primary-text", "surface-3", TEXT],
  ["primary-text", "primary-tint", TEXT],
  ["on-primary", "primary", TEXT], ["on-primary", "primary-hover", TEXT], ["on-primary", "primary-active", TEXT],
  ["on-primary-tint", "primary-tint", TEXT],
  ["accent-text", "canvas", TEXT], ["accent-text", "surface", TEXT],
  ["accent-text", "surface-2", TEXT], ["accent-text", "surface-3", TEXT],
  ["accent-text-hover", "canvas", TEXT], ["accent-text-hover", "surface", TEXT],
  ["accent-text-hover", "surface-2", TEXT],
  ["on-accent", "accent", TEXT], ["on-accent", "accent-hover", TEXT],
  ["on-accent-tint", "accent-tint", TEXT],
  ["on-error", "error", TEXT],
  ["error-text", "error-tint", TEXT], ["error-text", "surface", TEXT], ["error-text", "canvas", TEXT],
  ["success-text", "success-tint", TEXT], ["success-text", "surface", TEXT],
  ["warning-text", "warning-tint", TEXT], ["warning-text", "surface", TEXT],
  ["info-text", "info-tint", TEXT], ["info-text", "surface", TEXT], ["info-text", "canvas", TEXT],
  ["on-brand-band", "brand-band", TEXT], ["on-brand-band-soft", "brand-band", TEXT],
  ["brand-band", "on-brand-band", TEXT],
  // 1.4.11: boundaries, fills and icons that identify a component
  ["primary-line", "canvas", NON_TEXT], ["primary-line", "surface", NON_TEXT],
  // The amber fill is BOUNDED by accent-line, not by itself: over cream the
  // fill alone is 2,07:1. The hairline against the ground is the pair that
  // matters, and it is mandatory on every amber fill and every citation chip.
  ["accent-line", "canvas", NON_TEXT], ["accent-line", "surface", NON_TEXT],
  ["line-control", "canvas", NON_TEXT], ["line-control", "surface", NON_TEXT],
  ["line-control", "surface-2", NON_TEXT], ["line-control", "surface-3", NON_TEXT],
  ["error", "canvas", NON_TEXT], ["error-line", "canvas", NON_TEXT], ["error-line", "surface", NON_TEXT],
  ["on-brand-band-accent", "brand-band", NON_TEXT],
  ["primary-text", "canvas", NON_TEXT], // chevrons / icons
  // A status DOT carries no text, so it needs 3:1 on its own tint. Dots use
  // *-text, never *-line: warning-line on the dark warning tint is 2,21:1.
  ["warning-text", "warning-tint", NON_TEXT], ["success-text", "success-tint", NON_TEXT],
  ["info-text", "info-tint", NON_TEXT], ["error-text", "error-tint", NON_TEXT],
];

// The focus ring is two-tone: amber outside, near-black companion inside. Both
// tones are painted OUTSIDE the element's border box (outline-offset 2px, and
// the box-shadow spread fills exactly that gap), so the ground that has to
// separate them is the surface the focused element sits on, not the element's
// own fill. It clears 3:1 on a ground when EITHER tone does.
const FOCUS_GROUNDS = [
  "canvas", "surface", "surface-2", "surface-3", "primary-tint", "accent-tint",
  "error-tint", "info-tint", "success-tint", "brand-band",
];

let failures = 0;
for (const [name, map] of [["light", light], ["dark", dark]]) {
  for (const [fg, bg, min] of PAIRS) {
    const a = map.get(`--color-${fg}`);
    const b = map.get(`--color-${bg}`);
    if (!a || !b) { console.error(`FAIL [${name}] unknown token in ${fg}/${bg}`); failures++; continue; }
    const r = ratio(a, b);
    if (r < min) {
      console.error(`FAIL [${name}] ${fg} on ${bg}: ${r.toFixed(2)}:1 < ${min}`);
      failures++;
    }
  }
  for (const bg of FOCUS_GROUNDS) {
    const b = map.get(`--color-${bg}`);
    const best = Math.max(ratio(map.get("--color-focus"), b), ratio(map.get("--color-focus-contrast"), b));
    if (best < NON_TEXT) {
      console.error(`FAIL [${name}] focus ring on ${bg}: best tone ${best.toFixed(2)}:1 < ${NON_TEXT}`);
      failures++;
    }
  }
}
const total = (PAIRS.length + FOCUS_GROUNDS.length) * 2;
if (failures) { console.error(`${failures} of ${total} pairs FAIL`); process.exit(1); }
console.log(`contrast OK: ${total} pairs measured in both schemes, ${total} pass`);
