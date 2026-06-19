import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/lib/auth";

// Same-origin proxy for browser → FastAPI calls. Attaches the backend JWT
// from the Auth.js session so client components never handle the token.

// Server-side upstream: inside docker the public origin (NEXT_PUBLIC_API_URL,
// what the BROWSER sees) is not reachable — use the internal service URL.
const API_URL =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

// Only user-scoped API surfaces ride the proxy. Notably excluded:
// /ingestion/webhooks (machine auth via provider secrets, not user JWTs)
// and /s/* (public share links — no session should be attached).
const ALLOWED_PREFIXES = [
  "documents",
  "chat",
  "briefings",
  "enrichment",
  "shares",
  "ingestion",
  "users",
  "clinical",
  "billing",
];

function isAllowed(path: string[]): boolean {
  if (path.length === 0) return false;
  if (path[0] === "ingestion" && path[1] === "webhooks") return false;
  // The Stripe webhook is machine-auth (Stripe signature), never user-session;
  // it is exposed directly via nginx, not through this authed proxy.
  if (path[0] === "billing" && path[1] === "webhook") return false;
  return ALLOWED_PREFIXES.includes(path[0]);
}

async function proxy(request: NextRequest, path: string[]) {
  if (!isAllowed(path)) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }
  const session = await auth();
  const token = session?.jwt;
  if (!token) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const search = request.nextUrl.search;
  const target = `${API_URL}/${path.join("/")}${search}`;

  const headers = new Headers();
  headers.set("Authorization", `Bearer ${token}`);
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const body = hasBody ? await request.arrayBuffer() : undefined;

  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
  });

  const responseHeaders = new Headers();
  for (const h of ["content-type", "content-disposition", "cache-control", "retry-after"]) {
    const v = upstream.headers.get(h);
    if (v) responseHeaders.set(h, v);
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, ctx: Ctx) {
  return proxy(request, (await ctx.params).path);
}

export async function POST(request: NextRequest, ctx: Ctx) {
  return proxy(request, (await ctx.params).path);
}

export async function DELETE(request: NextRequest, ctx: Ctx) {
  return proxy(request, (await ctx.params).path);
}

export async function PUT(request: NextRequest, ctx: Ctx) {
  return proxy(request, (await ctx.params).path);
}

export async function PATCH(request: NextRequest, ctx: Ctx) {
  return proxy(request, (await ctx.params).path);
}
