// redact(text) -> { text, map }
//
// Replaces every identifier it recognises with a stable placeholder
// (`[DNI_1]`, `[NOMBRE_2]`) and returns the mapping back. The mapping stays on
// the device; the text is what may be sent.
//
// Properties this file guarantees, and that the tests pin down:
//   - Deterministic: the same input gives the same placeholders.
//   - Idempotent: redacting the output again changes nothing, because existing
//     placeholders are protected and never matched or re-minted.
//   - Reversible: rehydrate(redact(t).text, redact(t).map) === t, which is why
//     the same value is only shared between occurrences that are written
//     identically (the key is the exact original string).
//   - Clinical values are never touched: a hit that overlaps a dose or a
//     measurement is dropped, whatever detector produced it (see clinical.ts).

import { findClinicalValues } from "./clinical";
import { PATTERN_DETECTORS } from "./patterns";
import type { EntityKind, RedactionMap, RedactionResult, Span } from "./types";

export type RedactOptions = {
  /**
   * Mapping from earlier turns of the same conversation. Reused so that the
   * same DNI keeps the same placeholder across messages and a new one does not
   * collide with `[DNI_1]` already in the server-side history. The returned
   * map contains these entries too.
   */
  seed?: RedactionMap;
  /**
   * Names the app already knows (the child's, the parent's). Masked wherever
   * they appear as a capitalised word, with or without accents. This is the
   * deterministic way to get `[NOMBRE_n]` without a model.
   */
  names?: readonly string[];
  /** Person spans from the model-backed layer. Vetted before use, see below. */
  modelSpans?: readonly Span[];
};

/** `[DNI_1]`, `[CODIGO_POSTAL_12]`. The one definition, shared with rehydrate. */
export const PLACEHOLDER_SOURCE = "\\[[A-Z]+(?:_[A-Z]+)*_\\d+\\]";

type Candidate = Span & { priority: number };

// Priorities when two hits overlap. Validated identifiers beat anything else
// (see PATTERN_DETECTORS); a name the app knows beats a model's guess.
const NAME_PRIORITY = 45;
const MODEL_PRIORITY = 30;

// Particles that are part of a surname but must not be masked on their own.
const NAME_PARTICLES = new Set(["de", "del", "la", "las", "los", "el", "y", "e", "da", "di", "van", "von", "le", "du"]);

export function redact(text: string, options: RedactOptions = {}): RedactionResult {
  const seed = options.seed ?? {};

  // Regions no hit may overlap: placeholders already in the text, and clinical
  // quantities.
  const present = [...text.matchAll(new RegExp(PLACEHOLDER_SOURCE, "g"))];
  const clinical = findClinicalValues(text);
  const blocked: Array<[number, number]> = [
    ...present.map((m): [number, number] => [m.index, m.index + m[0].length]),
    ...clinical.map((c): [number, number] => [c.start, c.end]),
  ];

  const candidates: Candidate[] = [];
  for (const { priority, detect } of PATTERN_DETECTORS) {
    for (const s of detect(text)) candidates.push({ ...s, priority });
  }
  for (const s of nameSpans(text, options.names ?? [])) candidates.push({ ...s, priority: NAME_PRIORITY });
  for (const s of options.modelSpans ?? []) {
    if (acceptableModelSpan(text, s, clinical)) candidates.push({ ...s, priority: MODEL_PRIORITY });
  }

  const usable = candidates.filter(
    (c) => c.start < c.end && !blocked.some(([a, b]) => c.start < b && a < c.end),
  );
  const chosen = resolveOverlaps(usable);

  // Allocation. `used` holds every placeholder that must not be minted again.
  const map: RedactionMap = { ...seed };
  const used = new Set<string>([...Object.keys(seed), ...present.map((m) => m[0])]);
  const placeholderOf = new Map<string, string>();
  for (const [placeholder, value] of Object.entries(seed)) {
    placeholderOf.set(keyFor(labelOf(placeholder), value), placeholder);
  }

  let out = "";
  let cursor = 0;
  for (const c of chosen) {
    const original = text.slice(c.start, c.end);
    const key = keyFor(c.kind, original);
    let placeholder = placeholderOf.get(key);
    if (!placeholder) {
      placeholder = mint(c.kind, used);
      used.add(placeholder);
      placeholderOf.set(key, placeholder);
      map[placeholder] = original;
    }
    out += text.slice(cursor, c.start) + placeholder;
    cursor = c.end;
  }
  out += text.slice(cursor);

  return { text: out, map };
}

function keyFor(kind: string, original: string): string {
  return `${kind}\u0000${original}`;
}

function labelOf(placeholder: string): string {
  return placeholder.slice(1, placeholder.lastIndexOf("_"));
}

/** The smallest `[KIND_n]` not taken yet, so numbering follows order of first appearance. */
function mint(kind: EntityKind, used: Set<string>): string {
  for (let n = 1; ; n++) {
    const candidate = `[${kind}_${n}]`;
    if (!used.has(candidate)) return candidate;
  }
}

function resolveOverlaps(candidates: Candidate[]): Candidate[] {
  const ranked = [...candidates].sort(
    (a, b) => b.priority - a.priority || b.end - b.start - (a.end - a.start) || a.start - b.start,
  );
  const accepted: Candidate[] = [];
  for (const c of ranked) {
    if (!accepted.some((a) => c.start < a.end && a.start < c.end)) accepted.push(c);
  }
  return accepted.sort((a, b) => a.start - b.start);
}

/**
 * The model reads text; it does not know which words are medicines. Three
 * rules keep its mistakes from reaching the question:
 *   - a person is letters only: a span with a digit in it is something else;
 *   - a person starts with a capital: "dalsy", "fiebre" are never names;
 *   - a capitalised word right before a dose is a drug ("Dalsy 100 mg"), not a
 *     person. (Not applied before weights or ages: "Lucía 5 kg" is a child.)
 */
function acceptableModelSpan(
  text: string,
  s: Span,
  clinical: ReadonlyArray<{ start: number; end: number; kind: string }>,
): boolean {
  if (s.kind !== "NOMBRE" || s.end - s.start < 2) return false;
  const slice = text.slice(s.start, s.end);
  if (/\d/.test(slice) || !/^\p{Lu}/u.test(slice)) return false;
  return !clinical.some(
    (c) => c.kind === "dose" && c.start >= s.end && /^\s{0,2}$/.test(text.slice(s.end, c.start)),
  );
}

// --- known names -----------------------------------------------------------

/** Lower-case and strip accents one UTF-16 unit at a time, so offsets survive. */
function fold(s: string): string {
  let out = "";
  for (const ch of s) {
    const base = ch.length === 1 ? ch.normalize("NFD")[0].toLowerCase() : ch;
    out += base.length === ch.length ? base : ch;
  }
  return out;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function nameSpans(text: string, names: readonly string[]): Span[] {
  const wanted = new Set<string>();
  for (const full of names) {
    const trimmed = full.trim().replace(/\s+/g, " ");
    if (trimmed.length < 2) continue;
    wanted.add(trimmed);
    for (const part of trimmed.split(" ")) {
      if (part.length >= 3 && !NAME_PARTICLES.has(fold(part))) wanted.add(part);
    }
  }
  if (wanted.size === 0) return [];

  const haystack = fold(text);
  const out: Span[] = [];
  for (const name of wanted) {
    const source = fold(name).split(" ").map(escapeRegExp).join("\\s+");
    const re = new RegExp(`(?<![\\p{L}\\p{N}_])${source}(?![\\p{L}\\p{N}_])`, "gu");
    for (const m of haystack.matchAll(re)) {
      // A name is written with a capital. "la luz" is light, "Luz tiene fiebre"
      // is a child; matching case-insensitively would rewrite clinical text for
      // every child called Luz, Alba, Mar, Paz or Sol. A name typed entirely in
      // lower case is therefore not masked: the deliberate price of that rule.
      if (/^\p{Lu}/u.test(text.slice(m.index, m.index + 1))) {
        out.push({ start: m.index, end: m.index + m[0].length, kind: "NOMBRE" });
      }
    }
  }
  return out;
}
