import { join } from "node:path";

import urgent from "./urgent-questions.json";

// The pure half of the production smoke suite: settings, the rule on what may
// reach the agent, the age check of the example question and the JSON
// summary. No browser here, so e2e/prod-smoke-kit.spec.ts can pin all of it
// in CI without touching the live site.

export const DEFAULT_BASE_URL = "https://adelia.godi.ai";

/**
 * Sent with every request of a run, from the pages and from the suite's own
 * calls: the API serves it as usual and leaves it out of the funnel, the
 * analytics, the /r/ clicks and the usage counter (apps/api/adelia/qa_traffic.py,
 * apps/web/lib/qa-traffic.ts). Any test against production must send it.
 */
export const QA_HEADERS: Readonly<Record<string, string>> = { "X-AdelIA-QA": "1" };

/** Under the home folder, never a fixed /Users/... path: Hermes runs it too. */
export const SHOTS_ROOT = "dev/adelia-design/shots/prod-smoke";

export type SmokeSettings = {
  baseURL: string;
  /** undefined is Playwright's own Chromium; "chrome" on Santiago's Mac. */
  channel: string | undefined;
  runDir: string;
};

function stamp(now: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}_` +
    `${p(now.getHours())}-${p(now.getMinutes())}-${p(now.getSeconds())}`
  );
}

export function smokeSettings(
  env: Record<string, string | undefined>,
  { home, now }: { home: string; now: Date },
): SmokeSettings {
  return {
    baseURL: (env.PROD_SMOKE_URL || DEFAULT_BASE_URL).replace(/\/+$/, ""),
    channel: env.PW_CHANNEL || undefined,
    runDir: env.PROD_SMOKE_RUN_DIR || join(home, SHOTS_ROOT, stamp(now)),
  };
}

// --- what may reach the agent -------------------------------------------------

/**
 * The only messages a smoke run may send to the agent: red flags, answered in
 * code by the graph's `guard` node before any model (agent/graph.py). The API
 * suite checks they are red flags (tests/test_prod_smoke_questions.py).
 */
export const URGENT_QUESTIONS: readonly string[] = urgent.questions;

/** Any path that can make a model answer: the demo, the RAG chat, the agent. */
export function isModelPath(url: string): boolean {
  const path = new URL(url).pathname;
  return (
    /^\/api\/(demo\/ask|chat|agent)(\/|$)/.test(path) ||
    /^\/api\/backend\/(chat(\/|$)|agent\/turn$)/.test(path)
  );
}

/** Why this agent turn must not leave the browser, or null when it is safe. */
export function refuseModelTurn(body: unknown): string | null {
  if (!body || typeof body !== "object") return "no JSON body";
  const b = body as Record<string, unknown>;
  // A card confirmation runs the write node and a clarify answer is folded
  // into the message: neither is the bare red flag the guard is known to stop.
  if (b.card_action != null) return "card_action is not allowed in a smoke run";
  if (b.clarification != null) return "clarification is not allowed in a smoke run";
  const message = typeof b.message === "string" ? b.message : "";
  if (!URGENT_QUESTIONS.includes(message)) {
    return `message is not a red flag of the suite: ${JSON.stringify(message.slice(0, 80))}`;
  }
  return null;
}

// --- checks 6 and 7: the cookie banner and the admin page --------------------

export type Box = { x: number; y: number; width: number; height: number };

/** True when two boxes share any area; touching edges do not count. */
export function boxesOverlap(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/** A batch of the consented journeys (lib/analytics.ts), not the consent proof. */
export function isAnalyticsCollect(url: string): boolean {
  return new URL(url).pathname === "/api/analytics/collect";
}

/**
 * The fragments that appear in any of the bodies, raw, URL-encoded (either
 * form of the space) or in another case. Check 6 types a question it never
 * sends and asserts no analytics batch carries it.
 */
export function leakedFragments(bodies: string[], fragments: string[]): string[] {
  const haystack = bodies.join("\n").toLowerCase();
  return fragments.filter((f) =>
    [f, encodeURIComponent(f), f.replace(/ /g, "+")].some((form) =>
      haystack.includes(form.toLowerCase()),
    ),
  );
}

/** What only an admin may read: the visitor analytics and the API usage. */
export const ADMIN_READS: readonly string[] = [
  "/api/backend/analytics/access",
  "/api/backend/analytics/summary",
  "/api/backend/funnel/summary",
  "/api/backend/funnel/usage",
];

// Top-level keys of those answers (services/analytics.summary,
// routers/funnel). A refusal carries none of them.
const ADMIN_KEYS = [
  "totals", "daily", "funnel", "sources", "recent_sessions", "consent", "counters",
  "rows", "links", "estimated_usd", "active_accounts", "unpriced",
];

/** The admin figures a response body carries, in the order of ADMIN_KEYS. */
export function adminFigures(body: string): string[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return [];
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return [];
  return ADMIN_KEYS.filter((k) => k in (parsed as Record<string, unknown>));
}

// --- Lucía's age and the example question ------------------------------------

/** "Lucía · 5 meses" / "7 months" / "7 mois" / "20 días": whole months. */
export function monthsInGrowthMark(label: string): number | null {
  const m = /(\d+)\s*(meses|mes|months?|mois|días|dias|days?|jours?)/iu.exec(label);
  if (!m) return null;
  const n = Number(m[1]);
  return /^(d|j)/i.test(m[2]) ? Math.floor(n / 30.44) : n;
}

const AGE_IN_TEXT =
  /(\d+)\s*(?:-\s*)?(meses|mes|months?|mois|semanas|weeks?|semaines?|años?|years?|ans?|días|days?|jours?)\b/giu;

function toMonths(n: number, unit: string): number {
  const u = unit.toLowerCase();
  if (/^(semana|week|semaine)/.test(u)) return Math.floor(n / 4.345);
  if (/^(año|year|an)/.test(u)) return n * 12;
  if (/^(día|day|jour)/.test(u)) return Math.floor(n / 30.44);
  return n;
}

/** The ages a text names that are not the child's (all of them if unknown). */
export function foreignAges(text: string, childMonths: number | null): string[] {
  return [...text.matchAll(AGE_IN_TEXT)]
    .filter((m) => childMonths === null || toMonths(Number(m[1]), m[2]) !== childMonths)
    .map((m) => m[0]);
}

// --- the JSON summary ---------------------------------------------------------

export type CheckResult = {
  title: string;
  status: "passed" | "failed" | "timedOut" | "skipped" | "interrupted" | string;
  durationMs: number;
  error?: string;
  notes: string[];
  shots: string[];
};

/** A guest space the suite opened, and whether it is gone. */
export type GuestRecord = { id: string; erased: boolean; detail: string };

export type Summary = {
  ok: boolean;
  base_url: string;
  run_dir: string;
  started_at: string;
  checks: {
    id: string;
    title: string;
    /** null: did not run (a placeholder, or after a failure in its chain). */
    ok: boolean | null;
    status: string;
    detail: string;
    duration_ms: number;
    shots: string[];
  }[];
  guests: GuestRecord[];
};

/** "1.es Portada" -> "1.es"; a title with no number is its own id. */
export function checkId(title: string): string {
  const m = /^(\d+(?:\.[a-z]+)?)\s/.exec(title);
  return m ? m[1] : title;
}

const ANSI = /\u001b\[[0-9;]*m/g;

export function summarize(
  meta: { baseURL: string; runDir: string; startedAt: string },
  results: CheckResult[],
  guests: GuestRecord[] = [],
): Summary {
  const checks = results.map((r) => {
    const ok = r.status === "passed" ? true : r.status === "skipped" ? null : false;
    const detail =
      ok === false && r.error
        ? r.error.replace(ANSI, "").slice(0, 1500)
        : r.notes.length > 0
          ? r.notes.join("; ")
          : ok === null
            ? "not run"
            : ok
              ? "ok"
              : r.status;
    return {
      id: checkId(r.title),
      title: r.title,
      ok,
      status: r.status,
      detail,
      duration_ms: r.durationMs,
      shots: r.shots,
    };
  });
  return {
    ok:
      checks.every((c) => c.ok !== false) &&
      checks.some((c) => c.ok === true) &&
      guests.every((g) => g.erased),
    base_url: meta.baseURL,
    run_dir: meta.runDir,
    started_at: meta.startedAt,
    checks,
    guests,
  };
}
