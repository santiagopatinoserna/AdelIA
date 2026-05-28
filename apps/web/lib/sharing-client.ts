import { auth } from "@/lib/auth";
import { API_URL } from "@/lib/api-client";

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

async function authedHeaders(): Promise<Record<string, string>> {
  const session = await auth();
  const token = (session as { jwt?: string } | null)?.jwt;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

export const sharing = {
  async create(briefingId: string, ttlHours = 24): Promise<ShareLink> {
    const headers = await authedHeaders();
    const res = await fetch(`${API_URL}/shares`, {
      method: "POST",
      headers,
      body: JSON.stringify({ briefing_id: briefingId, ttl_hours: ttlHours }),
    });
    if (!res.ok) throw new Error(`sharing.create: ${res.status}`);
    return res.json();
  },

  async list(): Promise<ShareLink[]> {
    const headers = await authedHeaders();
    const res = await fetch(`${API_URL}/shares`, { headers, cache: "no-store" });
    if (!res.ok) throw new Error(`sharing.list: ${res.status}`);
    return res.json();
  },

  async revoke(token: string): Promise<void> {
    const headers = await authedHeaders();
    const res = await fetch(`${API_URL}/shares/${token}`, {
      method: "DELETE",
      headers,
    });
    if (!res.ok) throw new Error(`sharing.revoke: ${res.status}`);
  },

  pdfUrl(briefingId: string): string {
    return `${API_URL}/briefings/${briefingId}/pdf`;
  },

  publicPdfUrl(token: string): string {
    return `${API_URL}/s/${token}/pdf`;
  },
};
