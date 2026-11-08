// Test traffic stays out of the numbers (2026-11-08). The production smoke
// suite (e2e-prod/) and other agents' runs send X-AdelIA-QA: 1, and the API
// serves those requests as usual but leaves them out of the anonymous funnel,
// the analytics, the /r/ clicks and the usage counter
// (apps/api/adelia/qa_traffic.py). The browser reaches the API through this
// server's routes, which forward almost nothing on purpose, so each of them
// passes this one header on with qaHeaders().
//
// Hygiene for the figures, not security: it opens nothing and skips no limit.
// Do not hang anything else on it.
export const QA_HEADER = "X-AdelIA-QA";

/** `{ "X-AdelIA-QA": "1" }` when the incoming request is test traffic, else `{}`. */
export function qaHeaders(incoming: Headers | undefined | null): Record<string, string> {
  return incoming?.get(QA_HEADER)?.trim() === "1" ? { [QA_HEADER]: "1" } : {};
}
