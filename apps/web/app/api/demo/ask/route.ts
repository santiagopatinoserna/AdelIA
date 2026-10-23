import { NextResponse } from "next/server";

// The public demo's only write path (audit 4.6). Like /api/funnel and unlike
// /api/backend, it attaches no session: the whole point of /demo is that it
// works for someone who has no account, and a visitor's identity has no
// business travelling with a question about a fictional baby.
//
// Only the question, the locale and, on the second turn of a clarify (AGENT_GRAPH
// step 3), the button she pressed are forwarded. Until 2026-10-23 the third was
// dropped here, so every press asked the same question again; the API checks
// the value against the buttons it wrote. The API applies its own
// brakes (per-IP rate limit, a daily budget counted in Postgres, a length
// cap) and this handler adds nothing of its own beyond refusing a body that
// is not the expected shape.
//
// The path mirrors the API's own (/api/funnel/{event} -> /funnel/{event},
// /api/demo/ask -> /demo/ask) on purpose. The repo's Caddyfile proxies
// /api/* to the API with the prefix stripped, so under that reverse proxy
// the browser's request never reaches this handler and lands on the same API
// route anyway. Renaming either half would turn one deployment's working
// endpoint into the other's 404.
const API_URL =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export async function POST(request: Request) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid body" }, { status: 400 });
  }
  const { question, locale, clarification } = (payload ?? {}) as {
    question?: unknown;
    locale?: unknown;
    clarification?: unknown;
  };
  if (typeof question !== "string" || question.trim().length < 3) {
    return NextResponse.json({ detail: "Invalid question" }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${API_URL}/demo/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: question.trim(),
        locale: typeof locale === "string" ? locale : "es",
        ...clarificationOf(clarification),
      }),
      cache: "no-store",
    });
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return NextResponse.json({ detail: "Demo unavailable" }, { status: 503 });
  }
}

// Forward a clarification only in the shape the API accepts ({field, value},
// two short strings); anything else is dropped here rather than relayed.
function clarificationOf(raw: unknown): { clarification?: { field: string; value: string } } {
  if (!raw || typeof raw !== "object") return {};
  const { field, value } = raw as { field?: unknown; value?: unknown };
  if (typeof field !== "string" || typeof value !== "string") return {};
  if (field.length > 32 || value.length > 16) return {};
  return { clarification: { field, value } };
}
