import { NextResponse } from "next/server";

// The build this server runs. next.config.ts bakes the same id into Next's
// BUILD_ID and into the client bundle (NEXT_PUBLIC_BUILD_ID); open tabs poll
// this route to learn about a deploy (components/sw-register.tsx). Never
// cached: an edge-cached answer would hide the very deploy it announces.
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(
    { buildId: process.env.NEXT_PUBLIC_BUILD_ID ?? "dev" },
    { headers: { "Cache-Control": "no-store" } },
  );
}
