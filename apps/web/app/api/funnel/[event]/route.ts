import { NextResponse } from "next/server";

// The public half of the funnel (audit 4.8). Deliberately NOT part of
// /api/backend: that proxy attaches the session JWT and 401s without one, and
// a visit counter must work for a visitor who has no account and must not
// carry her identity when she does.
//
// Nothing of the incoming request is forwarded. No header, no cookie, no
// body, no IP: the upstream call is a bare POST whose entire payload is the
// event name, which is why the counter cannot describe anybody.
//
// The path mirrors the API's own (/api/funnel/{event} -> /funnel/{event}) on
// purpose. The repo's Caddyfile proxies /api/* to the API with the prefix
// stripped, so under that reverse proxy the browser's request never reaches
// this handler and lands on the same API route anyway. Renaming either half
// would turn one deployment's working endpoint into the other's 404.
const API_URL =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

const EVENTS = new Set(["visit", "start"]);

export async function POST(
  _request: Request,
  ctx: { params: Promise<{ event: string }> },
) {
  const { event } = await ctx.params;
  if (!EVENTS.has(event)) {
    return new NextResponse(null, { status: 204 });
  }
  try {
    await fetch(`${API_URL}/funnel/${event}`, { method: "POST", cache: "no-store" });
  } catch {
    // The API is down or slow. A missed count is not an incident, and the
    // page that called this is not waiting on the answer.
  }
  // Always 204: nobody reads this status, and an error body is one more thing
  // an unauthenticated caller could probe.
  return new NextResponse(null, { status: 204 });
}
