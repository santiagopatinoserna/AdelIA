import { NextResponse } from "next/server";

// The browser half of the consented journeys (lib/analytics.ts) posts here.
// Like /api/funnel, deliberately NOT /api/backend: that proxy attaches the
// session JWT, and a visitor's journey must never carry her account. Behind
// the production Caddyfile /api/* goes straight to the API with the prefix
// stripped and this handler is not reached; the path mirrors the API's
// (/api/analytics/collect -> /analytics/collect) so both routes work.
//
// Forwarded: the body as it came (sendBeacon's text/plain JSON), and only the
// headers the API decides with: the user agent (bot filter and device class,
// never stored), Sec-GPC (a refusal), and Cloudflare's client address and
// country, which the API believes only where TRUST_CF_CONNECTING_IP says
// Cloudflare is in front. No cookie, no Authorization.
const API_URL =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

const ACTIONS = new Set(["collect", "consent"]);
const FORWARDED = ["user-agent", "sec-gpc", "cf-connecting-ip", "cf-ipcountry", "content-type"];
const MAX_BODY = 64_000;

export async function POST(request: Request, ctx: { params: Promise<{ action: string }> }) {
  const { action } = await ctx.params;
  if (!ACTIONS.has(action)) return new NextResponse(null, { status: 204 });
  const body = await request.text().catch(() => "");
  if (body.length > MAX_BODY) return new NextResponse(null, { status: 204 });
  const headers = new Headers();
  for (const name of FORWARDED) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const res = await fetch(`${API_URL}/analytics/${action}`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
    });
    // The consent proof answers 422 to a malformed answer; pass that on so a
    // bug shows in the console. Everything else is a quiet 204.
    if (action === "consent" && res.status === 422) {
      return new NextResponse(null, { status: 422 });
    }
  } catch {
    // The API is down: a lost batch is not an incident.
  }
  return new NextResponse(null, { status: 204 });
}
