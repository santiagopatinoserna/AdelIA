import { basename, join, relative } from "node:path";

import { DEFAULT_BASE_URL } from "../kit";
import fixtures from "./fixtures.json";

// The pure half of the usability battery: the matrix, the first-screen
// budgets, what counts as a problem and how much it bothers a mother holding a
// baby with one hand free, the performance limits, the stubbed turns and the
// HTML report. No browser here: e2e/usability-kit.spec.ts pins all of it in
// CI. The browser half is page.ts.

/** Under the home folder, never a fixed /Users/... path: Hermes runs it too. */
export const USABILITY_SHOTS_ROOT = "dev/adelia-design/shots/usability";

export type UsabilitySettings = { baseURL: string; channel: string | undefined; runDir: string };

function stamp(now: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}_` +
    `${p(now.getHours())}-${p(now.getMinutes())}-${p(now.getSeconds())}`
  );
}

/** Same URL and browser variables as the smoke suite, its own run folder. */
export function usabilitySettings(
  env: Record<string, string | undefined>,
  { home, now }: { home: string; now: Date },
): UsabilitySettings {
  return {
    baseURL: (env.PROD_SMOKE_URL || DEFAULT_BASE_URL).replace(/\/+$/, ""),
    channel: env.PW_CHANNEL || undefined,
    runDir: env.USABILITY_RUN_DIR || join(home, USABILITY_SHOTS_ROOT, stamp(now)),
  };
}

// --- the matrix ---------------------------------------------------------------

export type Viewport = { name: string; width: number; height: number; phone: boolean };

/** A small Android, an iPhone, a large iPhone, and a tablet held upright. */
export const VIEWPORTS: readonly Viewport[] = [
  { name: "360", width: 360, height: 780, phone: true },
  { name: "390", width: 390, height: 844, phone: true },
  { name: "430", width: 430, height: 932, phone: true },
  { name: "tablet", width: 768, height: 1024, phone: false },
];

export const SCHEMES = ["light", "dark"] as const;
export const LOCALES = ["es", "en", "fr"] as const;
export type Locale = (typeof LOCALES)[number];

/**
 * The on-screen keyboard, as the height it takes away: about 40 % of a phone
 * (336 px of an iPhone's 844) and a bit less of a tablet. The page sees it as a
 * shorter viewport (`interactive-widget=resizes-content`).
 */
export function KEYBOARD_HEIGHT(v: Viewport): number {
  return Math.round(v.height * (v.phone ? 0.4 : 0.38));
}

// --- the first screen ---------------------------------------------------------

/**
 * What she has to take in before doing anything: distinct blocks of text or
 * controls, things she could tap, and words, all inside the first viewport.
 */
export type FirstScreen = { blocks: number; taps: number; words: number };

export function budgetKey(page: string, v: Viewport, locale: string): string {
  return `${page}.${v.name}.${locale}`;
}

/** Why this first screen is over its budget; empty when it is not. */
export function overBudget(
  measured: FirstScreen,
  budget: FirstScreen | undefined,
  key: string,
): string[] {
  if (!budget) return [`${key}: no budget recorded`];
  return (["blocks", "taps", "words"] as const)
    .filter((k) => measured[k] > budget[k])
    .map((k) => `${key}: ${k} ${measured[k]} > ${budget[k]}`);
}

// --- tap targets --------------------------------------------------------------

export type Target = {
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
  /** A link inside a sentence: WCAG 2.5.8 exempts it, the report still counts it. */
  inline: boolean;
};

export const MIN_TAP = 44;

/** Controls under 44 px on either side (sub-pixel rounding forgiven). */
export function smallTargets(targets: Target[], min = MIN_TAP): Target[] {
  return targets.filter((t) => !t.inline && (t.width < min - 0.05 || t.height < min - 0.05));
}

// --- issues and their order ---------------------------------------------------

/**
 * Ordered by what costs her most: missing a warning first, then not being
 * able to finish, then not being able to press or see what she types, then
 * reading in the wrong order, small targets, and last what only slows her.
 */
export const ISSUE_KINDS = {
  "safety-hidden": { weight: 100, label: "Un aviso, «Cuándo ir al médico» o la urgencia no se ven" },
  "urgent-no-call": { weight: 98, label: "La urgencia no ofrece llamar al 112 en un toque" },
  "journey-broken": { weight: 95, label: "Un recorrido no se puede terminar" },
  "control-covered": { weight: 90, label: "Algo tapa un botón o el campo" },
  "keyboard-covers": { weight: 85, label: "Con el teclado abierto no ve lo que escribe" },
  "clarify-thumb": { weight: 80, label: "La tarjeta de aclaración no se usa bien con un pulgar" },
  "reading-order": { weight: 75, label: "La respuesta no empieza por lo que tiene que hacer" },
  "small-target": { weight: 70, label: "Zonas táctiles de menos de 44 px" },
  "horizontal-scroll": { weight: 65, label: "La página se desplaza de lado" },
  "banner-covers": { weight: 62, label: "El banner de cookies tapa algo hasta que lo contesta" },
  slow: { weight: 60, label: "Tarda en verse o en poder escribir con red móvil" },
  "page-error": { weight: 55, label: "Errores de la página" },
  a11y: { weight: 50, label: "Accesibilidad (axe, serio o crítico)" },
  heavy: { weight: 45, label: "Demasiado JavaScript para una red móvil" },
  budget: { weight: 40, label: "La primera pantalla ha crecido" },
} as const;

export type IssueKind = keyof typeof ISSUE_KINDS;
export type Issue = { kind: IssueKind; where: string; detail: string };
export type RankedIssue = {
  kind: IssueKind;
  label: string;
  weight: number;
  detail: string;
  where: string[];
  count: number;
};

/** One line per problem, where it happens, most bothersome first. */
export function rankIssues(issues: Issue[]): RankedIssue[] {
  const groups = new Map<string, RankedIssue>();
  for (const i of issues) {
    const key = `${i.kind}\u0000${i.detail}`;
    const g = groups.get(key);
    if (g) {
      if (!g.where.includes(i.where)) g.where.push(i.where);
      g.count = g.where.length;
      continue;
    }
    const k = ISSUE_KINDS[i.kind];
    groups.set(key, { kind: i.kind, label: k.label, weight: k.weight, detail: i.detail, where: [i.where], count: 1 });
  }
  return [...groups.values()].sort(
    (a, b) => b.weight - a.weight || b.count - a.count || a.detail.localeCompare(b.detail),
  );
}

// --- performance --------------------------------------------------------------

/**
 * A mid-range phone (CPU four times slower) on a slow 4G line, as Lighthouse's
 * mobile profile. Chrome's emulation adds the latency once per request, not
 * per round trip, so the figures are kinder than a real phone's: they are for
 * comparing runs, not a promise. Each figure is the median of PERF_SAMPLES
 * cold loads. The limits sit about a half above what production measured on
 * 2026-11-11 (LCP about 0.8 s, typing about 2.1 s) and a quarter above its
 * JavaScript (136 to 231 KB), so they fail when it gets worse, not on noise.
 */
export const MOBILE_CPU_RATE = 4;
export const MOBILE_NETWORK = {
  offline: false,
  latency: 150,
  downloadThroughput: (1.6 * 1024 * 1024) / 8,
  uploadThroughput: (750 * 1024) / 8,
};
export const PERF_SAMPLES = 3;

export type PerfSample = { lcpMs?: number; typeMs?: number; jsKB?: number };
export type PerfPage = "landing" | "panel" | "settings" | "privacy";

export const PERF_LIMITS: Record<PerfPage, { lcpMs: number; typeMs: number; jsKB: number }> = {
  landing: { lcpMs: 1200, typeMs: 3200, jsKB: 250 },
  panel: { lcpMs: 1200, typeMs: 3300, jsKB: 265 },
  settings: { lcpMs: 1200, typeMs: 3300, jsKB: 290 },
  privacy: { lcpMs: 1200, typeMs: 3200, jsKB: 170 },
};

export function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function perfIssues(page: PerfPage, sample: PerfSample): Issue[] {
  const limit = PERF_LIMITS[page];
  const out: Issue[] = [];
  if (sample.lcpMs !== undefined && sample.lcpMs > limit.lcpMs)
    out.push({ kind: "slow", where: page, detail: `LCP ${Math.round(sample.lcpMs)} ms > ${limit.lcpMs} ms` });
  if (sample.typeMs !== undefined && sample.typeMs > limit.typeMs)
    out.push({ kind: "slow", where: page, detail: `escribir ${Math.round(sample.typeMs)} ms > ${limit.typeMs} ms` });
  if (sample.jsKB !== undefined && sample.jsKB > limit.jsKB)
    out.push({ kind: "heavy", where: page, detail: `JS ${Math.round(sample.jsKB)} KB > ${limit.jsKB} KB` });
  return out;
}

// --- journeys -----------------------------------------------------------------

export type JourneyStep = { name: string; taps: number; ms: number; ok: boolean };

export function journeyTotals(steps: JourneyStep[]) {
  return {
    taps: steps.reduce((n, s) => n + s.taps, 0),
    ms: steps.reduce((n, s) => n + s.ms, 0),
    ok: steps.every((s) => s.ok),
    failed: steps.filter((s) => !s.ok).map((s) => s.name),
  };
}

// --- stubbed turns ------------------------------------------------------------

type TurnBody = {
  message?: unknown;
  locale?: unknown;
  card_action?: unknown;
  clarification?: unknown;
  clarifications?: unknown;
};

function sse(events: [string, unknown][]): string {
  return events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
}

function planStream(locale: Locale): string {
  // In paragraphs, the way tokens arrive, so the page renders while it streams.
  const parts = fixtures.plan[locale].answer.split(/(?<=\n\n)/);
  return sse([
    ["start", {}],
    ...parts.map((content): [string, unknown] => ["token", { content }]),
    ["final", { citations: [], evidence_citations: [] }],
  ]);
}

/**
 * The SSE body that answers this agent turn inside the browser, or null when
 * the turn is not one of the fixtures (it then goes on to the model guard,
 * which only lets the smoke suite's red flags through). The plan message gets
 * the plan; the nursery worry gets the two-question clarify card, and the
 * same message sent back with the pressed answers gets the plan.
 */
export function stubTurnFor(body: TurnBody): string | null {
  if (!body || body.card_action != null || typeof body.message !== "string") return null;
  for (const locale of LOCALES) {
    if (body.message === fixtures.plan[locale].message) return planStream(locale);
    if (body.message === fixtures.clarify[locale].message) {
      if (body.clarification != null || body.clarifications != null) return planStream(locale);
      return sse([
        ["start", {}],
        ["card", { card: fixtures.clarify[locale].card }],
        ["final", { citations: [], evidence_citations: [] }],
      ]);
    }
  }
  return null;
}

// --- the report ---------------------------------------------------------------

export type ReportData = {
  baseURL: string;
  startedAt: string;
  runDir: string;
  checks: { id: string; title: string; ok: boolean | null; detail: string; durationMs: number }[];
  issues: Issue[];
  metrics: { section: string; key: string; values: Record<string, number | string> }[];
  journeys: { name: string; steps: JourneyStep[] }[];
  shots: string[];
  /** What a person saw in the shots and the battery does not measure. */
  observations?: string[];
};

function esc(s: unknown): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/\u2014/g, "-");
}

function table(head: string[], rows: (string | number)[][]): string {
  if (rows.length === 0) return "<p class=quiet>Sin datos.</p>";
  return (
    `<table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>` +
    rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("") +
    "</tbody></table>"
  );
}

function metricTable(data: ReportData, section: string): string {
  const rows = data.metrics.filter((m) => m.section === section);
  const cols = [...new Set(rows.flatMap((m) => Object.keys(m.values)))];
  return table(["", ...cols], rows.map((m) => [m.key, ...cols.map((c) => m.values[c] ?? "")]));
}

/** One self-contained HTML page next to the shots it shows. */
export function renderReport(data: ReportData): string {
  const ranked = rankIssues(data.issues);
  const failed = data.checks.filter((c) => c.ok === false).length;
  const passed = data.checks.filter((c) => c.ok === true).length;
  // One entry per kind of problem, in rankIssues' order, its cases under it.
  const kinds: { label: string; items: typeof ranked }[] = [];
  for (const r of ranked) {
    const last = kinds[kinds.length - 1];
    if (last && last.label === r.label) last.items.push(r);
    else kinds.push({ label: r.label, items: [r] });
  }
  const problems =
    ranked.length === 0
      ? "<p>Ningún problema encontrado.</p>"
      : "<ol class=problems>" +
        kinds
          .map((k) => {
            const places = new Set(k.items.flatMap((r) => r.where)).size;
            return (
              `<li><strong>${esc(k.label)}</strong> <span class=quiet>(${places} sitio(s))</span><ul>` +
              k.items
                .map(
                  (r) =>
                    `<li>${esc(r.detail)} <span class=quiet>· ${r.count}: ` +
                    `${esc(r.where.slice(0, 6).join(", "))}${r.where.length > 6 ? ` y ${r.where.length - 6} más` : ""}</span></li>`,
                )
                .join("") +
              "</ul></li>"
            );
          })
          .join("") +
        "</ol>";
  const observations = (data.observations ?? []).length
    ? `<h3>Visto en las capturas (no lo mide la batería)</h3><ul>${data.observations!.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>`
    : "";
  const journeys = data.journeys
    .map((j) => {
      const t = journeyTotals(j.steps);
      return (
        `<h3>${esc(j.name)}: ${t.taps} toques, ${(t.ms / 1000).toFixed(1)} s${t.ok ? "" : " (incompleto)"}</h3>` +
        table(
          ["Paso", "Toques", "Tiempo (ms)", "Bien"],
          j.steps.map((s) => [s.name, s.taps, Math.round(s.ms), s.ok ? "sí" : "no"]),
        )
      );
    })
    .join("");
  const shots = data.shots
    .map((s) => {
      const rel = relative(data.runDir, s) || basename(s);
      return `<figure><a href="${esc(rel)}"><img loading=lazy src="${esc(rel)}" alt="${esc(basename(s))}"></a><figcaption>${esc(basename(s, ".png"))}</figcaption></figure>`;
    })
    .join("");
  return `<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AdelIA: usabilidad ${esc(data.startedAt)}</title>
<style>
body{font:16px/1.5 system-ui,sans-serif;margin:0 auto;max-width:72rem;padding:1rem;color:#1d1f1c;background:#faf8f3}
h1{font-size:1.6rem}h2{margin-top:2.5rem;border-top:1px solid #ddd;padding-top:1rem}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{border:1px solid #ddd;padding:.3rem .5rem;text-align:left;vertical-align:top}
.quiet{color:#666;font-size:.85rem}.bad{color:#a3261b}.good{color:#1f6b3a}
ol.problems li{margin:.6rem 0}
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:.8rem}
figure{margin:0}img{width:100%;border:1px solid #ccc}figcaption{font-size:.75rem;color:#666;word-break:break-all}
</style></head><body>
<h1>Usabilidad de AdelIA</h1>
<p>${esc(data.baseURL)} · ${esc(data.startedAt)} · <span class=good>${passed} bien</span> · <span class=bad>${failed} con fallos</span> · ${ranked.length} problemas distintos</p>
<p class=quiet>Sin modelo: solo banderas rojas reales (el código responde antes de cualquier modelo); el plan y la tarjeta de aclaración son respuestas simuladas dentro del navegador (fixtures.json). Cabecera X-AdelIA-QA en todo.</p>
<h2>Problemas, de lo que más molesta a lo que menos</h2>
${problems}
${observations}
<h2>Recorridos</h2>
${journeys || "<p class=quiet>Sin datos.</p>"}
<h2>Rendimiento en móvil (CPU x${MOBILE_CPU_RATE}, 4G lenta, mediana de ${PERF_SAMPLES})</h2>
<p class=quiet>La latencia emulada se suma una vez por petición, no por ida y vuelta: cifras para comparar ejecuciones, más amables que un móvil real.</p>
${metricTable(data, "perf")}
<h2>Primera pantalla (bloques, toques, palabras)</h2>
${metricTable(data, "first-screen")}
<h2>Tarjeta de aclaración con un pulgar (simulada)</h2>
${metricTable(data, "clarify")}
<h2>Accesibilidad (axe)</h2>
${metricTable(data, "a11y")}
<h2>Comprobaciones</h2>
${table(
  ["Id", "Comprobación", "Resultado", "Detalle", "s"],
  data.checks.map((c) => [
    c.id,
    c.title,
    c.ok === null ? "no se ejecutó" : c.ok ? "bien" : "falla",
    c.detail.slice(0, 600),
    (c.durationMs / 1000).toFixed(1),
  ]),
)}
<h2>Capturas</h2>
<div class=shots>${shots}</div>
</body></html>
`;
}
