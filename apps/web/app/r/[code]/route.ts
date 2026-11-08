import { isLinkPreviewFetcher, looksLikeCode } from "@/lib/short-links";

// /r/<code>: our own short links for the social networks (2026-11-08). The
// community plan rules out bit.ly and the like, which add their own tracking,
// and a long UTM link does not fit a bio or a story sticker. The API holds the
// table (services/short_links.py): POST /funnel/link/<code> answers where the
// code goes and counts the click, one integer per day and code; GET answers
// without counting, for link previews. Nothing of the visitor's is forwarded:
// no cookie, no address, no user agent. Outside [locale] and outside the
// middleware (middleware.ts), so the code is read as typed.
//
// Always a 302 and never cached: a 301 would be remembered by the browser and
// the next tap would not be counted. Relative Location, so the redirect stays
// on whatever host the visitor used. An unknown code, a slow or absent API:
// the landing, without an error.
const API_URL =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

const LANDING = "/";
const API_TIMEOUT_MS = 1500;

function redirect(location: string): Response {
  return new Response(null, {
    status: 302,
    headers: { Location: location, "Cache-Control": "no-store" },
  });
}

async function resolve(code: string, count: boolean): Promise<string | null> {
  try {
    const res = await fetch(`${API_URL}/funnel/link/${encodeURIComponent(code)}`, {
      method: count ? "POST" : "GET",
      cache: "no-store",
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { location?: unknown };
    const location = typeof body.location === "string" ? body.location : "";
    // Our own paths only: never a redirect to another host.
    return /^\/[a-z]{2}(\?|$)/.test(location) ? location : null;
  } catch {
    return null;
  }
}

export async function GET(request: Request, ctx: { params: Promise<{ code: string }> }) {
  const { code } = await ctx.params;
  if (!looksLikeCode(code)) return redirect(LANDING);
  const count = !isLinkPreviewFetcher(request.headers.get("user-agent"));
  return redirect((await resolve(code, count)) ?? LANDING);
}

// A HEAD is a checker, never a person: same answer, nothing counted.
export async function HEAD(_request: Request, ctx: { params: Promise<{ code: string }> }) {
  const { code } = await ctx.params;
  if (!looksLikeCode(code)) return redirect(LANDING);
  return redirect((await resolve(code, false)) ?? LANDING);
}
