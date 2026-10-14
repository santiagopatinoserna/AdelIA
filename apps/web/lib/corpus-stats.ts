// Server-side read of GET /clinical/corpus-stats (adelia/services/corpus_stats.py).
//
// The landing used to print "118 fuentes" from the message catalogs. The
// 2026-08-31 audit asked for the figure to be generated (point 1.1), the fix
// only corrected the number, and six weeks later production held 127 sources
// and 301 chunks. The catalogs now carry the sentence and this module carries
// the number, counted by the API in the database that retrieval searches.
//
// Never import from a "use client" component: it reads the internal API URL.

const API_URL =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export type CorpusStats = {
  sources: number;
  chunks: number;
  year_min: number | null;
  year_max: number | null;
  sources_without_year: number;
  by_type: Record<string, number>;
};

// The API already caches for five minutes. This copy exists for the rate
// limiter, not for speed: every landing render comes from the web container,
// which the API sees as ONE client, so a fetch per visit would spend a shared
// budget on a number that changes once per deploy.
const FRESH_MS = 5 * 60 * 1000;
const TIMEOUT_MS = 2500;
// After a failure, do not ask again for this long: with the API down every
// landing render would otherwise wait out the timeout before painting.
const RETRY_AFTER_FAILURE_MS = 30 * 1000;

let cached: { at: number; value: CorpusStats } | null = null;
let failedAt: number | null = null;

export function resetCorpusStatsCache(): void {
  cached = null;
  failedAt = null;
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isYear(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isInteger(value));
}

// A payload that does not look like the contract is treated as no answer: a
// wrong shape must degrade to the figure-less landing, never print "NaN".
function parse(body: unknown): CorpusStats | null {
  if (typeof body !== "object" || body === null) return null;
  const b = body as Record<string, unknown>;
  if (!isCount(b.sources) || !isCount(b.chunks) || !isCount(b.sources_without_year)) return null;
  if (!isYear(b.year_min) || !isYear(b.year_max)) return null;
  if (typeof b.by_type !== "object" || b.by_type === null) return null;
  // An empty corpus has nothing to advertise.
  if (b.sources === 0) return null;
  return {
    sources: b.sources,
    chunks: b.chunks,
    year_min: b.year_min,
    year_max: b.year_max,
    sources_without_year: b.sources_without_year,
    by_type: b.by_type as Record<string, number>,
  };
}

type Deps = { fetcher?: typeof fetch; now?: () => number };

/**
 * The corpus counts, or null when the API cannot say.
 *
 * Null is a normal answer, not an error: the build runs without the API, and
 * so can a deploy for a minute. Callers render the sentence without a number
 * in that case. When a previous answer exists it is served stale instead,
 * because a figure that is five minutes old is still true and a blank is not
 * better.
 */
export async function getCorpusStats(deps: Deps = {}): Promise<CorpusStats | null> {
  const fetcher = deps.fetcher ?? fetch;
  const now = (deps.now ?? Date.now)();
  if (cached && now - cached.at < FRESH_MS) return cached.value;
  if (failedAt !== null && now - failedAt < RETRY_AFTER_FAILURE_MS) return cached?.value ?? null;
  try {
    const res = await fetcher(`${API_URL}/clinical/corpus-stats`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const value = res.ok ? parse(await res.json()) : null;
    if (!value) {
      failedAt = now;
      return cached?.value ?? null;
    }
    cached = { at: now, value };
    failedAt = null;
    return value;
  } catch {
    failedAt = now;
    return cached?.value ?? null;
  }
}
