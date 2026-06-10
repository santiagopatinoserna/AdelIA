import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/lib/auth";

// Same-origin proxy for browser → FastAPI calls. Attaches the backend JWT
// from the Auth.js session so client components never handle the token.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function proxy(request: NextRequest, path: string[]) {
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
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) responseHeaders.set("Content-Type", upstreamType);

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
