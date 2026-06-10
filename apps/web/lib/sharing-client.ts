// Browser sharing client ("use client" components). Authenticated calls go
// through the same-origin /api/backend proxy; public share URLs point at the
// API directly because they're meant to leave the app (QR, email, copy-link).

export interface ShareLink {
  token: string;
  briefing_id: string;
  expires_at: string;
  revoked: boolean;
  access_count: number;
  last_accessed_at: string | null;
  created_at: string;
  share_url: string;
}

// NEXT_PUBLIC_ vars are inlined into the client bundle at build time.
const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const sharing = {
  async create(briefingId: string, ttlHours = 24): Promise<ShareLink> {
    const res = await fetch("/api/backend/shares", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ briefing_id: briefingId, ttl_hours: ttlHours }),
    });
    if (!res.ok) throw new Error(`sharing.create: ${res.status}`);
    return res.json();
  },

  async list(): Promise<ShareLink[]> {
    const res = await fetch("/api/backend/shares", { cache: "no-store" });
    if (!res.ok) throw new Error(`sharing.list: ${res.status}`);
    return res.json();
  },

  async revoke(token: string): Promise<void> {
    const res = await fetch(`/api/backend/shares/${token}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`sharing.revoke: ${res.status}`);
  },

  // Owner download — needs auth, so it rides the proxy.
  pdfUrl(briefingId: string): string {
    return `/api/backend/briefings/${briefingId}/pdf`;
  },

  // Public link — signed by token, no session needed; must work outside the app.
  publicPdfUrl(token: string): string {
    return `${PUBLIC_API_URL}/s/${token}/pdf`;
  },
};
